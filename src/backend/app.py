"""Application assembly (docs/03_API_AND_FRONTEND.md, docs/04_SETUP_DEPLOY_VERIFY.md).

One object owns the wiring so that swapping a layer is a one-line change
and nothing downstream has to know which backend it got. That is the
practical payoff of the three-slot model: the L2 slot can be Gemini or
the offline stub, the L3 slot MiniMax or nothing at all, and the cascade,
the state machines and the API are identical either way.

Startup order is deliberate. The server must come up and serve ``/setup``
even when no provider is configured and no detector has been downloaded
(docs/04_SETUP_DEPLOY_VERIFY.md: "第一次啟動只需讓 Setup backend + frontend 可用"). So a missing
key demotes a layer to its stub or disables it — it never aborts boot.
"""

from __future__ import annotations

import threading
from typing import Any

from .api.ws import Broadcaster
from .cascade import Cascade
from .config import AppConfig, ProviderConfig, default_l2, default_l3
from .domain.policy import CarePolicy
from .domain.timeutil import now_ms
from .l1.detector import build_detector
from .l1.gate import PersonGate
from .l2.service import L2Service, build_gemini_l2, build_local_vllm_l2
from .l2.stub import StubL2Backend
from .l3.service import L3Service, build_local_vllm_l3, build_minimax_l3
from .l3.stub import StubL3Backend
from .legacy_flow import LegacyFlow
from .media.frames import FrameWindow
from .media.replay_source import ReplaySource, ScriptedSource
from .media.rtsp_source import RtspSource
from .notify.telegram import TelegramNotifier
from .observer.service import ObserverScheduler
from .care_logging import CareLogger, setup_system_logging
from .store import Database, Repositories, migrate


class AppContext:
    def __init__(self, config: AppConfig | None = None, *, use_stubs: bool | None = None) -> None:
        self.config = config or AppConfig()
        self.config.ensure_dirs()
        self.secrets = self.config.secret_store()

        self.db = Database(self.config.db_path)
        self.migrations_applied = migrate(self.db)
        self.repos = Repositories(self.db)
        self.logger = setup_system_logging(self.repos)
        self.logger.info("app", f"Care Agent v5 starting (subject={self.config.subject_id}, db={self.config.db_path})")

        self.policy = self._load_policy()
        self.l2_config: ProviderConfig = default_l2()
        self.l3_config: ProviderConfig = default_l3()

        self.broadcaster = Broadcaster()
        self.frames = FrameWindow(capacity=480)
        self.source: Any = None
        self.source_terminal: dict[str, Any] | None = None
        self.browser_sessions: dict[str, Any] = {}
        self._source_lock = threading.Lock()
        self.started_at_ms = now_ms()

        self.use_stubs = use_stubs
        self.detector = self._build_detector()
        self.gate = PersonGate(self.policy.l1)
        self.l2 = self._build_l2()
        self.l3 = self._build_l3()
        self.legacy_flow = LegacyFlow(
            self.repos, self.config.subject_id, self.l2.backend,
            use_stub=bool(self.use_stubs), model=self.l2_config.model,
        )
        self.notifier = self._build_notifier()
        self.cascade = self._build_cascade()
        self.observer = ObserverScheduler(self, self.config.observer_interval_sec)
        self.debug_simulator: Any = None
        if self.config.debug:
            from .debug.simulator import DebugSimulator
            self.debug_simulator = DebugSimulator(self)
        if self.notifier is not None:
            self.notifier.start_polling()
        self.observer.start()

    # -- configuration ---------------------------------------------------

    def _load_policy(self) -> CarePolicy:
        active = self.repos.active_config()
        if active is None:
            policy = CarePolicy()
            self.repos.save_config_version(policy.version, policy.to_dict(), "defaults")
            return policy
        return CarePolicy.from_dict(active["payload"])

    def apply_policy(self, payload: dict[str, Any], note: str = "") -> CarePolicy:
        """Persist a new config version and rebuild everything that reads it."""
        policy = CarePolicy.from_dict(payload)
        if policy.version == self.policy.version:
            # A change must be a new version, or rollback has nothing to
            # roll back to (docs/03_API_AND_FRONTEND.md §Settings).
            policy = policy.with_version(f"policy.v5.{now_ms()}")
        self.repos.save_config_version(policy.version, policy.to_dict(), note)
        self.policy = policy
        self.rebuild(reason="config_applied")
        return policy

    def rollback_policy(self, version: str) -> bool:
        if not self.repos.activate_config_version(version):
            return False
        active = self.repos.active_config()
        self.policy = CarePolicy.from_dict(active["payload"]) if active else CarePolicy()
        self.rebuild(reason="config_rollback")
        return True

    # -- layer construction ------------------------------------------------

    def _stub_mode(self, secret_key: str) -> bool:
        if self.use_stubs is not None:
            return self.use_stubs
        # Local vLLM normally has no API key.  Its reachability is checked by
        # the model call itself, so a missing key must not silently demote it.
        if secret_key == "VLLM_API_KEY":
            return False
        return not self.secrets.configured(secret_key)

    def _build_detector(self) -> Any:
        detector_id = self.policy.l1.detector_id
        try:
            if detector_id == "yolo11n":
                path = self.config.data_dir / "models" / "yolo11n.onnx"
                return build_detector(
                    "yolo11n",
                    model_path=str(path),
                    confidence_threshold=self.policy.l1.confidence_threshold,
                )
            if detector_id == "motion":
                return build_detector("motion")
            return build_detector("stub")
        except ValueError:
            self.repos.log("warn", "l1", f"unknown detector {detector_id!r}, falling back to stub")
            return build_detector("stub")

    def _build_l2(self) -> L2Service:
        if not self.l2_config.enabled:
            return L2Service(StubL2Backend(), provider="disabled", redact=self.secrets.redact)
        if self._stub_mode(self.l2_config.secret_key):
            return L2Service(StubL2Backend(), provider="stub", redact=self.secrets.redact)
        if self.l2_config.name == "local_vllm":
            return build_local_vllm_l2(
                api_key=self.secrets.get(self.l2_config.secret_key) or "",
                model=self.l2_config.model,
                base_url=self.l2_config.base_url,
                timeout_sec=self.l2_config.timeout_sec,
                redact=self.secrets.redact,
            )
        return build_gemini_l2(
            api_key=self.secrets.get(self.l2_config.secret_key) or "",
            model=self.l2_config.model,
            base_url=self.l2_config.base_url,
            timeout_sec=self.l2_config.timeout_sec,
            inline_limit_bytes=self.config.inline_limit_bytes,
            redact=self.secrets.redact,
        )

    def _build_l3(self) -> L3Service | None:
        if not self.policy.escalation.enabled or not self.l3_config.enabled:
            return None
        if self._stub_mode(self.l3_config.secret_key):
            return L3Service(StubL3Backend(), provider="stub", redact=self.secrets.redact)
        if self.l3_config.name == "local_vllm":
            return build_local_vllm_l3(
                api_key=self.secrets.get(self.l3_config.secret_key) or "",
                model=self.l3_config.model,
                base_url=self.l3_config.base_url,
                timeout_sec=self.l3_config.timeout_sec,
                redact=self.secrets.redact,
            )
        return build_minimax_l3(
            api_key=self.secrets.get(self.l3_config.secret_key) or "",
            model=self.l3_config.model,
            base_url=self.l3_config.base_url,
            timeout_sec=self.l3_config.timeout_sec,
            wire_format="frames",
            max_frames=10,
            redact=self.secrets.redact,
        )

    def _build_notifier(self) -> TelegramNotifier | None:
        """Only a real token *and* an allow-listed chat make this live.

        A token with no configured recipient is not "almost configured" —
        there is nowhere to send, so the Policy Gateway must keep treating
        notification as unavailable and downgrading to a dashboard alert.
        """
        if self.config.debug:
            return None
        token = self.secrets.get("TELEGRAM_BOT_TOKEN")
        chats = self.policy.notification.telegram_chat_ids
        if not token or not chats:
            return None
        return TelegramNotifier(token, chats, self.repos, redact=self.secrets.redact)

    def _build_cascade(self) -> Cascade:
        return Cascade(
            policy=self.policy,
            repos=self.repos,
            detector=self.detector,
            gate=self.gate,
            l2_service=self.l2,
            l3_service=self.l3,
            legacy_flow=self.legacy_flow,
            frames=self.frames,
            clips_dir=self.config.clips_dir,
            subject_id=self.config.subject_id,
            broadcast=self.broadcaster.publish,
            telegram_configured=self.notifier is not None and self.notifier.configured,
            notifier=self.notifier,
            runtime_mode=self.config.runtime_mode,
        )

    def rebuild(self, reason: str = "manual") -> None:
        """Rebuild the layers against the current policy and secrets."""
        was_running = bool(self.cascade._threads)
        self.cascade.stop()
        if self.notifier is not None:
            self.notifier.stop_polling()
        self.detector = self._build_detector()
        self.gate = PersonGate(self.policy.l1)
        self.l2 = self._build_l2()
        self.l3 = self._build_l3()
        self.legacy_flow.shutdown()
        self.legacy_flow = LegacyFlow(
            self.repos, self.config.subject_id, self.l2.backend,
            use_stub=bool(self.use_stubs), model=self.l2_config.model,
        )
        self.notifier = self._build_notifier()
        self.cascade = self._build_cascade()
        if self.notifier is not None:
            self.notifier.start_polling()
        if was_running:
            self.cascade.start()
        self.repos.log("info", "app", f"layers rebuilt ({reason})",
                       {"config_version": self.policy.version})

    # -- sources -----------------------------------------------------------

    def start_source(self, kind: str, target: str, **kwargs: Any) -> dict[str, Any]:
        """Attach a frame source. Replay and RTSP are interchangeable here."""
        with self._source_lock:
            self.stop_source()
            self.frames.reset()
            self.cascade.reset_source_state()
            self.source_terminal = None
            if kind == "replay_scenario":
                path = self.config.replay_dir / f"{target}.json"
                source: Any = ScriptedSource.from_file(path, fps=self.policy.cadence.clip_fps,
                                                       realtime=True,
                                                       on_terminal=self._on_source_terminal)
            elif kind == "replay_file":
                source = ReplaySource(target, fps=self.policy.cadence.clip_fps,
                                      on_terminal=self._on_source_terminal, **kwargs)
            elif kind == "rtsp":
                source = RtspSource(target, fps=self.policy.cadence.clip_fps, **kwargs)
            else:
                raise ValueError(f"unknown source kind: {kind!r}")

            self.source = source
            source.start(self.cascade.ingest)
            self.cascade.start()
            self.repos.log("info", "source", f"started {kind}", {"kind": kind})
            return source.health()

    def start_scripted_source(self, manifest: dict[str, Any], source_id: str) -> dict[str, Any]:
        with self._source_lock:
            self.stop_source()
            self.frames.reset()
            self.cascade.reset_source_state()
            self.source_terminal = None
            source = ScriptedSource(
                manifest, source_id=source_id, fps=self.policy.cadence.clip_fps,
                realtime=True, on_terminal=self._on_source_terminal,
            )
            self.source = source
            source.start(self.cascade.ingest)
            self.cascade.start()
            self.repos.log("info", "source", "started debug scenario", {"source_id": source_id})
            return source.health()

    def _on_source_terminal(self, lifecycle: str, error: str | None) -> None:
        try:
            self.source_terminal = {"lifecycle": lifecycle, "error": error, "at_ms": now_ms()}
            if lifecycle in {"completed", "failed"}:
                self.cascade.stop()
            level = "error" if lifecycle == "failed" else "info"
            self.repos.log(level, "source", f"source {lifecycle}", {"error": error} if error else {})
            source_id = str(getattr(self.source, "source_id", ""))
            if self.config.debug and source_id.startswith("simulation:"):
                simulation_id = source_id.split(":", 1)[1]
                self.db.execute(
                    "UPDATE simulation_runs SET status=?, completed_at_ms=? WHERE simulation_id=?",
                    (lifecycle, now_ms(), simulation_id))
            self.broadcaster.publish("source.lifecycle", self.source_terminal)
        finally:
            # Source callbacks run on their own thread; release its thread-local
            # SQLite handle once the terminal event is recorded.
            self.db.close()

    def stop_source(self) -> None:
        if self.source is not None:
            try:
                self.source.stop()
            except Exception:  # noqa: BLE001
                pass
            self.source = None

    def reset_history(self) -> dict[str, Any]:
        """Stop live inputs and clear runtime history, preserving settings."""
        with self._source_lock:
            self.stop_source()
        for session in list(self.browser_sessions.values()):
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass
        self.browser_sessions.clear()
        self.cascade.stop()
        self.cascade.reset()
        self.source_terminal = None
        self.observer.reset()
        deleted = self.repos.clear_history()
        self.broadcaster.reset()
        self.broadcaster.publish("history.reset", {
            "preserved": ["config_versions", "schema_migrations", "secrets"],
            "deleted": deleted,
        })
        return {"deleted": deleted,
                "preserved": ["config_versions", "schema_migrations", "secrets"]}

    def shutdown(self) -> None:
        if self.debug_simulator is not None:
            self.debug_simulator.stop_stream()
        for session in list(self.browser_sessions.values()):
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass
        self.logger.info("app", "Care Agent v5 shutting down")
        self.browser_sessions.clear()
        self.stop_source()
        self.observer.stop()
        if self.notifier is not None:
            self.notifier.stop_polling()
        self.cascade.stop()
        self.legacy_flow.shutdown()
        self.db.close()

    # -- status ------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "uptime_ms": now_ms() - self.started_at_ms,
            "runtime": {"mode": self.config.runtime_mode, "debug": self.config.debug},
            "subject_id": self.config.subject_id,
            "config_version": self.policy.version,
            "migrations_applied": self.migrations_applied,
            "source": self.source.health() if self.source else {"running": False, "lifecycle": "stopped"},
            "browser_media": [session.health() for session in self.browser_sessions.values()],
            "cascade": self.cascade.status(),
            "realtime": self.broadcaster.metrics(),
            "observer": self.observer.status(),
            "providers": {
                "l2": {**self.l2_config.describe(self.secrets),
                       "active": getattr(self.l2.backend, "model", None),
                       "stub": isinstance(self.l2.backend, StubL2Backend)},
                "l3": {**self.l3_config.describe(self.secrets),
                       "active": getattr(getattr(self.l3, "backend", None), "model", None),
                       "stub": self.l3 is not None and isinstance(self.l3.backend, StubL3Backend)},
            },
            "legacy_flow": {
                "provider": self.legacy_flow.provider,
                "model": self.legacy_flow.model,
                "pending_main_agent": len(self.legacy_flow._pending),
            },
            "secrets": self.secrets.describe(),
        }
