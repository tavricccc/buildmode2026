"""REST route table (docs/03_API_AND_FRONTEND.md §API).

Handlers take ``(ctx, request)`` and return ``(status, payload)``. Two
rules hold across all of them:

* No handler ever returns a secret. Only ``SecretStore.describe()``
  crosses this boundary (docs/04_SETUP_DEPLOY_VERIFY.md §Secrets).
* Anything that changes behaviour writes a config version first, so the
  Dashboard's rollback list is complete by construction.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from ..config import PROVIDER_LABELS, SLOT_PROVIDERS, provider_config
from ..domain.enums import L2Outcome
from ..domain.timeutil import day_key, now_ms
from ..l1.detector import DETECTOR_REGISTRY, build_detector
from ..l2.gemini_client import GeminiClient, GeminiError
from ..l3.minimax_client import MiniMaxClient, MiniMaxError
from ..media import ffmpeg
from ..media.replay_source import ScriptedSource
from ..observer.daily import run_comprehensive_review
from ..secretstore import SECRET_KEYS


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class Request:
    def __init__(self, method: str, path: str, query: dict[str, list[str]],
                 body: dict[str, Any], params: dict[str, str]) -> None:
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.params = params

    def q(self, name: str, default: str = "") -> str:
        return self.query.get(name, [default])[0]

    def q_int(self, name: str, default: int) -> int:
        try:
            return int(self.q(name, str(default)))
        except ValueError:
            return default


Handler = Callable[[Any, Request], "tuple[int, Any] | tuple[int, Any, str]"]
ROUTES: list[tuple[str, re.Pattern[str], Handler]] = []


def route(method: str, pattern: str) -> Callable[[Handler], Handler]:
    compiled = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def register(handler: Handler) -> Handler:
        ROUTES.append((method, compiled, handler))
        return handler

    return register


# ---------------------------------------------------------------------
# Status and telemetry
# ---------------------------------------------------------------------


@route("GET", "/api/status")
def get_status(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, ctx.status()


@route("GET", "/api/pipeline/runs")
def get_runs(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """The audit view: every window, whatever happened to it."""
    outcome = request.q("l2_outcome") or None
    if outcome and outcome not in {o.value for o in L2Outcome}:
        raise ApiError(400, "bad_outcome", f"unknown l2_outcome {outcome!r}")
    limit = min(request.q_int("limit", 50), 500)
    runs = ctx.repos.list_runs(limit=limit, offset=request.q_int("offset", 0), l2_outcome=outcome)
    window_ms = request.q_int("stats_window_sec", 3600) * 1000
    return 200, {"runs": runs, "stats": ctx.repos.run_stats(now_ms() - window_ms)}


@route("GET", "/api/observations")
def get_observations(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """Return every saved L2 observation, newest first, bounded by the UI request."""
    return 200, {"observations": ctx.repos.list_observations(
        ctx.config.subject_id, min(request.q_int("limit", 12), 200),
    )}


@route("GET", "/api/logs")
def get_logs(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"logs": ctx.repos.recent_logs(min(request.q_int("limit", 100), 500),
                                               request.q("level") or None)}


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------


@route("GET", "/api/events")
def get_events(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"events": ctx.repos.list_events(
        limit=min(request.q_int("limit", 50), 200),
        event_type=request.q("type") or None,
        status=request.q("status") or None,
    )}


@route("GET", "/api/events/{event_id}")
def get_event(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """One event plus its full cascade trace (docs/03_API_AND_FRONTEND.md §Dashboard)."""
    event = ctx.repos.get_event(request.params["event_id"])
    if event is None:
        raise ApiError(404, "not_found", "no such event")
    runs = ctx.repos.runs_for_event(event["event_id"])
    calls: list[dict[str, Any]] = []
    for run in runs:
        for column in ("l2_call_id", "l3_call_id"):
            call_id = run.get(column)
            if call_id:
                row = ctx.db.query_one("SELECT * FROM model_calls WHERE call_id=?", (call_id,))
                if row is not None:
                    calls.append(dict(row))
    analyses = [dict(r) for r in ctx.db.query(
        "SELECT * FROM analyses WHERE event_id=? ORDER BY created_at", (event["event_id"],))]
    actions = [dict(r) for r in ctx.db.query(
        "SELECT * FROM actions WHERE event_id=? ORDER BY created_at", (event["event_id"],))]
    return 200, {"event": event, "runs": runs, "model_calls": calls,
                 "analyses": analyses, "actions": actions}


@route("GET", "/api/hydration/summary")
def get_hydration(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    summary = ctx.repos.hydration_summary(request.q("day") or None)
    summary["target_ml"] = ctx.policy.hydration.daily_target_ml
    total = summary.get("total_ml", 0) or 0
    summary["progress"] = round(total / summary["target_ml"], 3) if summary["target_ml"] else 0.0
    return 200, summary


@route("GET", "/api/actions")
def get_actions(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"actions": ctx.repos.list_actions(min(request.q_int("limit", 50), 200))}


# ---------------------------------------------------------------------
# Original Longcare-compatible Main Agent, memory and interaction
# ---------------------------------------------------------------------


@route("GET", "/api/agent/runs")
def get_agent_runs(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"runs": ctx.repos.list_agent_runs(
        limit=min(request.q_int("limit", 50), 200),
        agent_name=request.q("agent") or None,
    )}


@route("POST", "/api/agent/main")
def post_main_agent(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    observation = request.body.get("observation")
    if not isinstance(observation, dict):
        raise ApiError(400, "bad_request", "observation object is required")
    window = request.body.get("window")
    if not isinstance(window, dict):
        window = {"window_id": f"api:{now_ms()}", "frame_count": 0}
    result = ctx.legacy_flow.run_main_agent(
        window=window, observation=observation,
        persisted=request.body.get("persisted") if isinstance(request.body.get("persisted"), dict) else {},
        trigger_type=str(request.body.get("trigger_type", "api_request")),
    )
    return 200, result


@route("GET", "/api/memory")
def get_memory(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"memories": ctx.repos.list_memories(
        ctx.config.subject_id, request.q("status") or None,
        min(request.q_int("limit", 50), 200),
    )}


@route("POST", "/api/memory/{memory_id}/status")
def post_memory_status(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    status = str(request.body.get("status", ""))
    if not ctx.repos.set_memory_status(request.params["memory_id"], status):
        raise ApiError(404, "not_found", "memory not found or status invalid")
    return 200, {"memory_id": request.params["memory_id"], "status": status}


@route("GET", "/api/interaction/messages")
def get_interaction_messages(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    conversation_id = request.q("conversation_id", "default")
    return 200, {"messages": ctx.repos.interaction_messages(
        ctx.config.subject_id, conversation_id, min(request.q_int("limit", 40), 200),
    )}


@route("POST", "/api/interaction/turn")
def post_interaction_turn(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    text = str(request.body.get("text", "")).strip()
    if not text:
        raise ApiError(400, "bad_request", "text is required")
    result = ctx.legacy_flow.interaction(
        text, str(request.body.get("conversation_id", "default")),
    )
    return 200, result


@route("POST", "/api/interaction/understanding")
def post_interaction_understanding(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, ctx.legacy_flow.understanding(
        str(request.body.get("conversation_id", "default")),
    )


# ---------------------------------------------------------------------
# Health and transcripts
# ---------------------------------------------------------------------


@route("GET", "/api/health/current")
def get_health(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"samples": ctx.repos.latest_health(ctx.config.subject_id)}


@route("POST", "/api/health/sample")
def post_health(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """Fake-health injection retained from v4 (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md §必做)."""
    metric = str(request.body.get("metric", "")).strip()
    if not metric:
        raise ApiError(400, "bad_request", "metric is required")
    try:
        value = float(request.body.get("value"))
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "value must be a number") from None
    sample_id = ctx.repos.save_health_sample(
        ctx.config.subject_id, metric, value,
        str(request.body.get("unit", "")), str(request.body.get("source", "fake")),
        int(request.body.get("observed_at_ms", now_ms())),
    )
    return 201, {"sample_id": sample_id}


@route("GET", "/api/transcripts")
def get_transcripts(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    since = request.q_int("since_ms", now_ms() - 600_000)
    ctx.repos.sweep_transcripts()
    return 200, {"since_ms": since,
                 "text": ctx.repos.recent_transcript(ctx.config.subject_id, since)}


@route("POST", "/api/transcripts")
def post_transcript(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    text = str(request.body.get("text", "")).strip()
    if not text:
        raise ApiError(400, "bad_request", "text is required")
    ended = int(request.body.get("ended_at_ms", now_ms()))
    transcript_id = ctx.repos.save_transcript(
        ctx.config.subject_id, text,
        int(request.body.get("started_at_ms", ended - 5000)), ended,
        float(request.body.get("confidence", 0.0)),
        int(request.body.get("ttl_sec", 3600)),
    )
    return 201, {"transcript_id": transcript_id}


# ---------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------


@route("GET", "/api/observer/findings")
def get_findings(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"findings": ctx.repos.list_findings(min(request.q_int("limit", 30), 100)),
                 "summaries": ctx.repos.daily_summaries(min(request.q_int("days", 14), 90))}


@route("GET", "/api/observer/status")
def get_observer_status(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    records = ctx.repos.list_observer_runs(ctx.config.subject_id, 1)
    return 200, {"scheduler": ctx.observer.status(),
                 "latest": records[0] if records else None}


@route("GET", "/api/observer/records")
def get_observer_records(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    limit = min(request.q_int("limit", 50), 200)
    return 200, {"records": ctx.repos.list_observer_runs(ctx.config.subject_id, limit)}


@route("GET", "/api/statistics")
def get_statistics(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    days = max(1, min(request.q_int("days", 30), 90))
    since_ms = now_ms() - days * 86_400_000
    return 200, {
        "days": days,
        "summaries": ctx.repos.daily_summaries(days, day_key(since_ms)),
        "observer_status_counts": ctx.repos.observer_status_counts(
            ctx.config.subject_id, since_ms),
        "recent_observations": ctx.repos.list_observer_runs(
            ctx.config.subject_id, min(days * 8, 200), since_ms),
        "health_samples": ctx.repos.health_history(
            ctx.config.subject_id, since_ms, min(days * 100, 1000)),
    }


@route("POST", "/api/observer/run")
def post_observer(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    result = ctx.observer.run_now()
    if result is None:
        raise ApiError(409, "observer_busy", "observer is already running")
    return 200, result


@route("POST", "/api/observer/analyze-all")
def post_comprehensive_review(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    days = request.body.get("days", 7)
    if not isinstance(days, int) or isinstance(days, bool) or days not in {1, 3, 7, 30}:
        raise ApiError(400, "bad_period", "days must be one of 1, 3, 7, or 30")
    result = run_comprehensive_review(ctx, days)
    if not result.get("ok"):
        if result.get("error") == "l3_disabled":
            raise ApiError(409, "l3_disabled", "L3 is disabled in the current policy")
        raise ApiError(502, str(result.get("error", "l3_failed")),
                       str(result.get("message", "L3 could not complete the review")))
    return 200, result


# ---------------------------------------------------------------------
# Settings and secrets
# ---------------------------------------------------------------------


@route("GET", "/api/settings")
def get_settings(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {
        "policy": ctx.policy.to_dict(),
        "providers": {"l2": ctx.l2_config.describe(ctx.secrets),
                      "l3": ctx.l3_config.describe(ctx.secrets)},
        # The menu comes from the backend so Settings cannot offer a
        # provider this build has no adapter for.
        "provider_options": {
            slot: [{"name": name,
                    "label": PROVIDER_LABELS.get(name, name),
                    "secret_key": provider_config(slot, name).secret_key,
                    "default_model": provider_config(slot, name).model}
                   for name in names]
            for slot, names in SLOT_PROVIDERS.items()
        },
        "secrets": ctx.secrets.describe(),
        "detectors": DETECTOR_REGISTRY,
        "versions": ctx.repos.list_config_versions(),
        # Host-managed, shown so an operator knows why they cannot edit them.
        "host_managed": {
            "data_dir": str(ctx.config.data_dir),
            "db_path": str(ctx.config.db_path),
            "bind": f"{ctx.config.host}:{ctx.config.port}",
        },
    }


@route("PUT", "/api/settings")
def put_settings(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    payload = request.body.get("policy")
    if not isinstance(payload, dict):
        raise ApiError(400, "bad_request", "policy object is required")
    policy = ctx.apply_policy(payload, note=str(request.body.get("note", "")))
    return 200, {"policy": policy.to_dict(), "version": policy.version}


@route("POST", "/api/settings/rollback")
def post_rollback(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    version = str(request.body.get("version", ""))
    if not ctx.rollback_policy(version):
        raise ApiError(404, "not_found", f"no config version {version!r}")
    return 200, {"policy": ctx.policy.to_dict(), "version": ctx.policy.version}


@route("POST", "/api/settings/providers")
def post_providers(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """Provider / model id / base URL / timeout per slot.

    L2 and L3 are independent by design (docs/03_API_AND_FRONTEND.md), so each slot is switched
    on its own. Switching replaces the slot's config with that provider's
    defaults rather than patching ``name``: the base URL, API style and
    secret key belong to the provider, and keeping a vLLM URL in a Gemini
    slot would look configured and fail on the first call. Any model or
    base URL sent in the same request is applied on top, so the UI can
    switch and rename in one round trip.
    """
    for slot in ("l2", "l3"):
        update = request.body.get(slot)
        if not isinstance(update, dict):
            continue
        config = getattr(ctx, f"{slot}_config")

        name = update.get("name")
        if isinstance(name, str) and name.strip() and name.strip() != config.name:
            try:
                config = provider_config(slot, name.strip())
            except ValueError as exc:
                raise ApiError(400, "unknown_provider", str(exc)) from exc
            setattr(ctx, f"{slot}_config", config)

        for field in ("model", "base_url"):
            if isinstance(update.get(field), str) and update[field].strip():
                setattr(config, field, update[field].strip())
        if isinstance(update.get("timeout_sec"), (int, float)):
            config.timeout_sec = float(update["timeout_sec"])
        if isinstance(update.get("enabled"), bool):
            config.enabled = update["enabled"]
    ctx.rebuild(reason="providers_updated")
    return 200, {"l2": ctx.l2_config.describe(ctx.secrets),
                 "l3": ctx.l3_config.describe(ctx.secrets)}


@route("POST", "/api/secrets")
def post_secret(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """Write-only. The response says 'configured', never the value."""
    key = str(request.body.get("key", ""))
    if key not in SECRET_KEYS:
        raise ApiError(400, "unknown_secret", f"{key!r} is not a known secret")
    ctx.secrets.set(key, str(request.body.get("value", "")))
    ctx.rebuild(reason=f"secret_{key.lower()}_updated")
    return 200, {"secrets": ctx.secrets.describe()}


# ---------------------------------------------------------------------
# Setup and integration probes (docs/03_API_AND_FRONTEND.md §Setup / Settings)
# ---------------------------------------------------------------------


@route("GET", "/api/setup/state")
def get_setup(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """What Setup still needs. Nothing here downloads anything (docs/04_SETUP_DEPLOY_VERIFY.md)."""
    detector_health = ctx.detector.health()
    scenarios = sorted(p.stem for p in (ctx.config.data_dir / "replays").glob("*.json"))
    steps = [
        {"id": "runtime", "label": "Runtime & FFmpeg",
         "done": ffmpeg.available(), "detail": ffmpeg.version()},
        {"id": "storage", "label": "Database",
         "done": ctx.config.db_path.exists(), "detail": str(ctx.config.db_path)},
        {"id": "l1", "label": "L1 person detector",
         "done": detector_health.get("status") in {"ok", "degraded"},
         "detail": f"{ctx.policy.l1.detector_id}: {detector_health.get('status')}"},
        {"id": "l2", "label": f"{ctx.l2_config.name} (L2)",
         "done": ctx.l2_config.name == "local_vllm" or ctx.secrets.configured(ctx.l2_config.secret_key),
         "detail": f"{ctx.l2_config.model} @ {ctx.l2_config.base_url}"},
        {"id": "l3", "label": f"{ctx.l3_config.name} (L3)",
         "done": ctx.l3_config.name == "local_vllm" or ctx.secrets.configured(ctx.l3_config.secret_key),
         "detail": f"{ctx.l3_config.model} @ {ctx.l3_config.base_url}"},
        {"id": "source", "label": "Camera or replay",
         "done": ctx.source is not None,
         "detail": "replay scenarios: " + (", ".join(scenarios) or "none")},
    ]
    return 200, {"steps": steps, "complete": all(s["done"] for s in steps),
                 "detectors": DETECTOR_REGISTRY, "scenarios": scenarios}


@route("POST", "/api/integrations/person-gate/test")
def test_person_gate(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    detector_id = str(request.body.get("detector_id", ctx.policy.l1.detector_id))
    frames = ctx.frames.buffer.latest(2)
    if not frames:
        raise ApiError(409, "no_frames", "start a source before testing L1")
    try:
        detector = (ctx.detector if detector_id == ctx.policy.l1.detector_id
                    else build_detector(detector_id))
    except ValueError as exc:
        raise ApiError(400, "unknown_detector", str(exc)) from None
    started = time.perf_counter()
    readings = [detector.detect(frame).to_dict() for frame in frames]
    return 200, {"detector_id": detector_id, "readings": readings,
                 "health": detector.health(),
                 "elapsed_ms": int((time.perf_counter() - started) * 1000)}


@route("POST", "/api/integrations/gemini/test")
def test_gemini(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """Auth + model reachability. No media, so it is cheap and safe to repeat."""
    key = ctx.secrets.get("GEMINI_API_KEY")
    if not key:
        raise ApiError(409, "not_configured", "GEMINI_API_KEY is not set")
    client = GeminiClient(key, model=ctx.l2_config.model, base_url=ctx.l2_config.base_url,
                          timeout_sec=min(ctx.l2_config.timeout_sec, 20.0))
    started = time.perf_counter()
    try:
        models = client.list_models()
    except GeminiError as exc:
        return 200, {"ok": False, "code": exc.code,
                     "message": ctx.secrets.redact(exc.message)[:300]}
    return 200, {"ok": True, "elapsed_ms": int((time.perf_counter() - started) * 1000),
                 "model_configured": ctx.l2_config.model,
                 "model_available": ctx.l2_config.model in models,
                 "models_visible": len(models)}


@route("POST", "/api/integrations/minimax/test")
def test_minimax(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    key = ctx.secrets.get("MINIMAX_API_KEY")
    if not key:
        raise ApiError(409, "not_configured", "MINIMAX_API_KEY is not set")
    client = MiniMaxClient(key, model=ctx.l3_config.model, base_url=ctx.l3_config.base_url,
                           timeout_sec=min(ctx.l3_config.timeout_sec, 20.0))
    started = time.perf_counter()
    try:
        models = client.list_models()
    except MiniMaxError as exc:
        return 200, {"ok": False, "code": exc.code,
                     "message": ctx.secrets.redact(exc.message)[:300]}
    return 200, {"ok": True, "elapsed_ms": int((time.perf_counter() - started) * 1000),
                 "model_configured": ctx.l3_config.model,
                 "model_available": ctx.l3_config.model in models,
                 "models_visible": len(models)}


@route("POST", "/api/pipeline/cascade-test")
def cascade_test(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    """One window through all three layers, against whatever is configured.

    This is the E2E check docs/03_API_AND_FRONTEND.md puts at the end of Setup: it proves the
    layers agree on a contract, not merely that each one answers a ping.
    """
    scenario = str(request.body.get("scenario", "fall"))
    path = ctx.config.data_dir / "replays" / f"{scenario}.json"
    if not path.exists():
        raise ApiError(404, "no_scenario", f"no replay scenario {scenario!r}")

    source = ScriptedSource.from_file(path, fps=ctx.policy.cadence.clip_fps, realtime=False)
    frames = source.frames(base_ms=now_ms() - 10_000)
    if not frames:
        raise ApiError(400, "empty_scenario", "scenario produced no frames")
    for frame in frames[-64:]:
        ctx.cascade.ingest(frame)
    for _ in range(max(2, ctx.policy.l1.frames_to_enter)):
        ctx.cascade._sample_once()

    decision = ctx.cascade.decide_window(now_ms())
    forced = type(decision)(L2Outcome.called, "cascade_test", decision.high_risk)
    run = ctx.cascade.run_window(forced, now_ms())

    escalation = ctx.cascade.l3_queue.take(timeout=0.1)
    if escalation is not None:
        try:
            ctx.cascade._run_escalation(*escalation.payload)
        finally:
            ctx.cascade.l3_queue.finish()

    return 200, {
        "scenario": scenario,
        "l1": {"decision": run.l1_decision, "detector": run.l1_detector_id},
        "l2": {"outcome": run.l2_outcome, "model": run.l2_model, "latency_ms": run.l2_latency_ms,
               "repaired": run.l2_repaired, "error": run.l2_error,
               "escalation": run.l2_escalation_reasons},
        "l3": {"outcome": run.l3_outcome, "model": run.l3_model, "latency_ms": run.l3_latency_ms,
               "risk": run.l3_risk_level, "error": run.l3_error},
        "run_id": run.run_id,
        "trace": run.trace(),
    }


# ---------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------


@route("GET", "/api/media/streams")
def get_media_streams(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    return 200, {"active": [session.health() for session in ctx.browser_sessions.values()],
                 "source": ctx.source.health() if ctx.source else {"running": False}}


@route("GET", "/api/replay/scenarios")
def get_scenarios(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    out = []
    for path in sorted((ctx.config.data_dir / "replays").glob("*.json")):
        try:
            manifest = ScriptedSource.from_file(path).manifest
        except (OSError, ValueError):
            continue
        out.append({"id": path.stem, "name": manifest.get("name", path.stem),
                    "description": manifest.get("description", ""),
                    "segments": len(manifest.get("segments", []))})
    return 200, {"scenarios": out}


@route("POST", "/api/source/start")
def post_source_start(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    kind = str(request.body.get("kind", "replay_scenario"))
    target = str(request.body.get("target", "fall"))
    try:
        health = ctx.start_source(kind, target)
    except (ValueError, OSError) as exc:
        raise ApiError(400, "source_failed", str(exc)) from None
    return 200, {"source": health}


@route("POST", "/api/source/stop")
def post_source_stop(ctx: Any, request: Request) -> tuple[int, dict[str, Any]]:
    ctx.stop_source()
    ctx.cascade.stop()
    return 200, {"stopped": True}


@route("GET", "/api/source/snapshot")
def get_source_snapshot(ctx: Any, request: Request) -> tuple[int, Any, str]:
    frames = ctx.frames.buffer.latest(1)
    if not frames:
        raise ApiError(404, "no_frame", "no source frame is available yet")
    return 200, frames[0].jpeg, "image/jpeg"
