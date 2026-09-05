from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import File, Form, FastAPI, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent import MainAgentPolicy, build_main_agent_context, build_main_agent_notes, evaluate_change_gate
from .adapters import FrigateAdapter, MiniMaxAdapter, TelegramAdapter, VllmVisionAdapter
from .change_gate import detect_frame_change
from .config import get_settings
from .db import Database
from .frigate_mqtt import FrigateMqttWorker
from .media_stream import VirtualCameraBridge
from .replay import ReplayManager
from .schemas import AudioTranscriptRequest, CaptureStatusRequest, FrigateEventRequest, HealthScenarioRequest, MainAgentJudgment, ModelDownloadRequest, ReplayLoadRequest, SetupSettingsPatch, SourceActivateRequest, VadActivityRequest, WindowRequest, VisionObservation
from .store import Store, make_id, now_iso, parse_dt


settings = get_settings()
db = Database(settings.database_path)
store = Store(db, settings)


class Broadcaster:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.sequence = 0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        await ws.send_json({"message_id": "snapshot", "type": "system.status", "occurred_at": now_iso(), "payload": status_payload(), "schema_version": "realtime.v1"})

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, message: dict[str, Any]) -> None:
        self.sequence += 1
        envelope = {"message_id": f"msg_{self.sequence}", "occurred_at": now_iso(), "schema_version": "realtime.v1", **message}
        stale = []
        for client in list(self.clients):
            try:
                await client.send_json(envelope)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


broadcaster = Broadcaster()
replay = ReplayManager(store, broadcaster.send)
minimax = MiniMaxAdapter(settings)
frigate = FrigateAdapter(settings)
telegram = TelegramAdapter(settings)
vllm = VllmVisionAdapter(settings)
jobs: dict[str, dict[str, Any]] = {}


vlm_health: dict[str, Any] = {"status": "degraded" if settings.local_vlm_mode == "stub" else "unavailable", "detail": "not_probed"}
minimax_health: dict[str, Any] = {"status": "unavailable", "detail": "not_probed"}
main_agent_health: dict[str, Any] = {"status": "disabled" if not settings.main_agent_enabled else "unavailable", "detail": "not_started"}
# One shared semaphore lets observation and main-agent calls run concurrently
# while keeping the total number of in-flight Omni requests bounded.
vllm_semaphore = asyncio.Semaphore(settings.vllm_max_concurrency)
main_agent_tasks: set[asyncio.Task] = set()
main_agent_policy = MainAgentPolicy(settings)
scene_locks: dict[str, asyncio.Lock] = {}


async def ensure_scene_context(session, image_bytes: tuple[bytes, ...], window: dict[str, Any]) -> dict[str, Any]:
    if session.scene_context:
        return session.scene_context
    lock = scene_locks.setdefault(session.id, asyncio.Lock())
    async with lock:
        if session.scene_context:
            return session.scene_context
        await broadcaster.send({"type": "scene.bootstrap.started", "correlation_id": session.id,
                                "payload": {"stream_id": session.id, "window_id": window["window_id"], "window_seconds": window.get("window_seconds", 5)}})
        async with vllm_semaphore:
            result = await vllm.analyze_scene(image_bytes, window)
        if result.status != "healthy":
            session.scene_context = {"location": "unknown", "scene_description": "scene bootstrap unavailable", "objects": [], "non_person_features": [], "uncertainty_reasons": [result.error_code or "scene_analysis_failed"], "confidence": 0.0}
            await broadcaster.send({"type": "scene.bootstrap.failed", "correlation_id": session.id,
                                    "payload": {"stream_id": session.id, "scene": session.scene_context, "error_code": result.error_code}})
            return session.scene_context
        scene = result.payload["scene"]
        input_hash = hashlib.sha256(json.dumps({"window": window, "scene": scene}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with db.transaction() as conn:
            call_id = store.add_model_call(conn, provider=settings.inference_provider, model=settings.inference_model, purpose="scene_bootstrap",
                                            input_hash=input_hash, prompt_version="scene-description.nemotron-omni.v1",
                                            schema_version=scene.get("schema_version", "scene-description.v1"), status="valid",
                                            response=scene, latency_ms=result.latency_ms)
        saved = store.record_scene_context(stream_id=session.id, scene=scene, model_call_id=call_id, started_at=session.started_at)
        session.scene_context_id = saved["id"]
        session.scene_context = {**scene, "scene_context_id": saved["id"], "stream_id": session.id}
        await broadcaster.send({"type": "scene.bootstrap.completed", "correlation_id": session.id,
                                "payload": {"stream_id": session.id, "scene_context": session.scene_context, "model": settings.inference_model, "latency_ms": result.latency_ms}})
        return session.scene_context


async def handle_change_gate(session, image_bytes: tuple[bytes, ...], window: dict[str, Any], audio_pcm: bytes | None) -> None:
    """Run the cheap L0 gate and only promote changed windows to L1 VLM."""
    gate = detect_frame_change(image_bytes, threshold=settings.change_gate_threshold,
                                audio_pcm=audio_pcm, previous_audio_level=session.last_gate_audio_level,
                                audio_delta_threshold=settings.change_gate_audio_delta_threshold,
                                min_changed_pairs=settings.change_gate_min_changed_pairs,
                                strong_score_multiplier=settings.change_gate_strong_score_multiplier)
    session.last_gate_audio_level = gate.get("audio_level")
    saved = store.record_change_gate(stream_id=session.id, window=window, gate=gate)
    window = {**window, "change_gate_triggered": bool(gate["changed"]), "change_gate": saved,
              "change_summary": gate.get("change_summary", ""), "change_reasons": gate.get("change_reasons", [])}
    if gate["changed"]:
        session.gate_changed_windows += 1
    if session.scene_context is None:
        await ensure_scene_context(session, image_bytes, window)
    await broadcaster.send({"type": "change_gate.completed", "correlation_id": window["window_id"],
                            "payload": {"stream_id": session.id, "window": window, "gate": saved,
                                        "changed": bool(gate["changed"]), "change_summary": gate.get("change_summary", ""),
                                        "method": gate.get("method", "local_pixel_delta")}})
    if not gate["changed"]:
        return

    session.observation_windows += 1
    session.vlm_windows += 1
    session.vlm_window_frames = len(image_bytes)
    if audio_pcm is not None:
        session.audio_windows += 1
    observation_window = {**window, "window_id": f"{session.id}:o{session.observation_windows}",
                          "stage": "observation", "source_gate_window_id": window["window_id"]}
    await handle_vllm_window(session, image_bytes, observation_window, audio_pcm)


async def handle_vllm_window(session, image_bytes: tuple[bytes, ...], window: dict[str, Any], audio_pcm: bytes | None) -> None:
    if settings.local_vlm_mode not in {"vllm", "real"}:
        return
    scene_context = await ensure_scene_context(session, image_bytes, window)
    async with vllm_semaphore:
        await broadcaster.send({"type": "local_analysis.started", "correlation_id": window["window_id"], "payload": {"stream_id": session.id, "window": window, "model": settings.inference_model, "source": "continuous_media_window_sampler"}})
        result = await vllm.analyze_window(image_bytes, audio_pcm=audio_pcm, scene_context=scene_context)
    if result.status != "healthy":
        store.log("warning", "local_vlm", "VLM observation was rejected", context={"stream_id": session.id, "status": result.status, "error_code": result.error_code})
        return
    observation = VisionObservation.model_validate(result.payload["observation"])
    observation = observation.model_copy(update={"observed_at_offset_ms": window["end_offset_ms"], "supporting_frame_indexes": observation.supporting_frame_indexes or list(range(window["frame_count"]))})
    gate = evaluate_change_gate(session.last_observation, observation, {"events": [], "recognition_events": []}, session.gate_event_keys)
    local_gate_trigger = bool(window.get("change_gate_triggered"))
    local_gate_reasons = list(window.get("change_reasons") or [])
    if gate["trigger"] or local_gate_trigger:
        observation = observation.model_copy(update={
            "change_detected": True,
            "change_confidence": max(float(observation.change_confidence), float(gate["change_confidence"]), 0.80 if local_gate_trigger else 0.0),
            "change_reasons": list(dict.fromkeys([*observation.change_reasons, *local_gate_reasons, *gate["reasons"]]))[:12],
            "change_summary": observation.change_summary or window.get("change_summary", ""),
        })
    session.last_observation = observation
    session.gate_event_keys = set(gate["event_keys"])
    window = {**window, "change_gate_triggered": gate["trigger"], "change_gate_reasons": gate["reasons"], "change_gate_events": gate["noteworthy_events"]}
    persisted = store.process_observation(observation, session.id, "vllm", window_metadata=window)
    session.last_state_tracker = persisted.get("state_tracker")
    post_persist_gate = evaluate_change_gate(session.last_observation, observation, persisted, session.gate_event_keys)
    session.gate_event_keys.update(post_persist_gate["event_keys"])
    all_gate_reasons = list(dict.fromkeys([*local_gate_reasons, *gate["reasons"], *post_persist_gate["reasons"]]))[:12]
    all_gate_events = list(dict.fromkeys([*gate["noteworthy_events"], *post_persist_gate["noteworthy_events"]]))[:12]
    if post_persist_gate["trigger"] and not observation.change_detected:
        observation = observation.model_copy(update={"change_detected": True, "change_confidence": post_persist_gate["change_confidence"], "change_reasons": all_gate_reasons})
        session.last_observation = observation
    window = {**window, "change_gate_triggered": bool(local_gate_trigger or gate["trigger"] or post_persist_gate["trigger"]), "change_gate_reasons": all_gate_reasons, "change_gate_events": all_gate_events}
    session.vlm_status = "active"
    store.log("info", "flow_model", "Multimodal window observation accepted", context={"stream_id": session.id, "window_id": window["window_id"], "frame_count": window["frame_count"], "audio_present": window["audio_present"], "audio_duration_ms": window["audio_duration_ms"], "provider": settings.inference_provider, "model": settings.inference_model, "person_visible": observation.person_visible, "posture": observation.posture, "vertical_transition": observation.vertical_transition, "audio_events": observation.audio_events, "speaker_emotion": observation.speaker_emotion, "speech_detected": observation.speech_detected, "transcript_saved": bool(persisted.get("transcript")), "confidence": observation.confidence})
    await broadcaster.send({"type": "local_analysis.completed", "correlation_id": window["window_id"], "payload": {"stream_id": session.id, "window": window, "scene_context": scene_context, "model": settings.inference_model, "provider": settings.inference_provider, "observation": observation.model_dump(), "state_tracker": persisted.get("state_tracker"), "events": persisted["events"], "recognition_events": persisted["recognition_events"], "transcript": persisted.get("transcript"), "latency_ms": result.latency_ms}})
    if persisted.get("transcript"):
        await broadcaster.send({"type": "audio.transcript", "correlation_id": window["window_id"], "payload": persisted["transcript"]})
    for event in [*persisted["events"], *persisted["recognition_events"]]:
        await broadcaster.send({"type": "event.updated", "correlation_id": event["id"], "payload": event})
    if gate["trigger"] or post_persist_gate["trigger"] or observation.warning_signal != "none":
        detail_reason = observation.warning_signal if observation.warning_signal != "none" else (all_gate_events[0] if all_gate_events else "change_detected")
        detail_snapshot = media_bridge.trigger_detail(session, reason=detail_reason, source_window_id=window["window_id"])
        await broadcaster.send({"type": "detail.sampling.triggered", "correlation_id": window["window_id"],
                                "payload": {"stream_id": session.id, "source_window_id": window["window_id"],
                                            "change_detected": window["change_gate_triggered"], "warning_signal": observation.warning_signal,
                                            "change_reasons": window["change_gate_reasons"], "stream": detail_snapshot}})
    meaningful_change = bool(window["change_gate_triggered"] or persisted.get("events") or persisted.get("recognition_events") or observation.warning_signal != "none")
    periodic_due = session.last_main_agent_mono is None or (time.monotonic() - session.last_main_agent_mono) >= settings.main_agent_interval_seconds
    if settings.main_agent_enabled and (meaningful_change or periodic_due) and len(main_agent_tasks) < settings.main_agent_max_pending:
        session.last_main_agent_mono = time.monotonic()
        task = asyncio.create_task(run_main_agent(session, window, observation, persisted), name=f"main-agent-{window['window_id']}")
        main_agent_tasks.add(task)
        task.add_done_callback(main_agent_tasks.discard)
    elif settings.main_agent_enabled and (meaningful_change or periodic_due):
        store.log("warning", "main_agent", "Main-agent queue is full; window deferred", context={"window_id": window["window_id"], "pending": len(main_agent_tasks), "max_pending": settings.main_agent_max_pending})
        await broadcaster.send({"type": "agent.analysis.skipped", "correlation_id": window["window_id"], "payload": {"window_id": window["window_id"], "reason": "pending_limit", "max_pending": settings.main_agent_max_pending}})


async def handle_detail_window(session, image_bytes: tuple[bytes, ...], window: dict[str, Any], audio_pcm: bytes | None) -> None:
    scene_context = session.scene_context or {"location": "unknown", "scene_description": "not initialized"}
    await broadcaster.send({"type": "detail.description.started", "correlation_id": window["window_id"],
                            "payload": {"stream_id": session.id, "window": window, "scene_context": scene_context, "model": settings.inference_model}})
    async with vllm_semaphore:
        result = await vllm.analyze_visual_description(image_bytes, window, scene_context=scene_context, audio_pcm=audio_pcm)
    if result.status != "healthy":
        store.log("warning", "visual_description", "5fps visual description failed", context={"stream_id": session.id, "window_id": window["window_id"], "error_code": result.error_code})
        await broadcaster.send({"type": "detail.description.failed", "correlation_id": window["window_id"],
                                "payload": {"stream_id": session.id, "window": window, "error_code": result.error_code}})
        return
    description = result.payload["description"]
    input_hash = hashlib.sha256(json.dumps({"window": window, "description": description}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with db.transaction() as conn:
        call_id = store.add_model_call(conn, provider=settings.inference_provider, model=settings.inference_model, purpose="visual_description",
                                        input_hash=input_hash, prompt_version="visual-description.nemotron-omni.v1",
                                        schema_version=description.get("schema_version", "visual-description.v1"), status="valid",
                                        response=description, latency_ms=result.latency_ms)
    saved = store.record_visual_description(stream_id=session.id, window={**window, "description_type": "detail"},
                                             description=description, model_call_id=call_id, scene_context_id=session.scene_context_id)
    await broadcaster.send({"type": "detail.description.completed", "correlation_id": window["window_id"],
                            "payload": {"stream_id": session.id, "window": window, "scene_context": scene_context,
                                        "description": saved, "model": settings.inference_model, "latency_ms": result.latency_ms}})
    if description.get("warning_level") != "none" or description.get("changes"):
        await broadcaster.send({"type": "detail.attention.signal", "correlation_id": window["window_id"],
                                "payload": {"stream_id": session.id, "window_id": window["window_id"],
                                            "warning_level": description.get("warning_level", "none"),
                                            "changes": description.get("changes", []), "warnings": description.get("warnings", [])}})


async def handle_focus_window(session, image_bytes: tuple[bytes, ...], window: dict[str, Any], audio_pcm: bytes | None) -> None:
    context = window.get("focus_context") or {}
    scene_context = session.scene_context or {"location": "unknown", "scene_description": "not initialized"}
    await broadcaster.send({"type": "focus.review.started", "correlation_id": window["window_id"],
                            "payload": {"stream_id": session.id, "window": window, "model": settings.inference_model}})
    async with vllm_semaphore:
        result = await vllm.analyze_focus(image_bytes, context=context, scene_context=scene_context, audio_pcm=audio_pcm)
    if result.status != "healthy":
        store.log("warning", "focus_review", "2fps focus review failed", context={"stream_id": session.id, "window_id": window["window_id"], "error_code": result.error_code})
        await broadcaster.send({"type": "focus.review.failed", "correlation_id": window["window_id"],
                                "payload": {"stream_id": session.id, "window": window, "error_code": result.error_code}})
        return
    focus = result.payload["focus"]
    input_hash = hashlib.sha256(json.dumps({"window": window, "context": context, "focus": focus}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with db.transaction() as conn:
        call_id = store.add_model_call(conn, provider=settings.inference_provider, model=settings.inference_model, purpose="focus_review",
                                        input_hash=input_hash, prompt_version="focus-review.nemotron-omni.v1",
                                        schema_version=focus.get("schema_version", "focus-review.v1"), status="valid",
                                        response=focus, latency_ms=result.latency_ms)
    saved = store.record_focus_review(stream_id=session.id, window=window, focus=focus, model_call_id=call_id)
    await broadcaster.send({"type": "focus.review.completed", "correlation_id": window["window_id"],
                            "payload": {"stream_id": session.id, "window": window, "focus": saved,
                                        "model": settings.inference_model, "latency_ms": result.latency_ms}})
    if focus.get("abnormal") or focus.get("warning_level") != "none":
        store.log("warning", "focus_review", "Focus review produced warning", context={"stream_id": session.id, "window_id": window["window_id"], "warning_level": focus.get("warning_level"), "confidence": focus.get("confidence")})
        await broadcaster.send({"type": "warning.created", "correlation_id": window["window_id"],
                                "payload": {"stream_id": session.id, "window_id": window["window_id"],
                                            "warning_level": focus.get("warning_level", "possible"), "description": focus.get("description"),
                                            "next_action": focus.get("next_action"), "action_executed": False}})


async def run_main_agent(session, window: dict[str, Any], observation: VisionObservation,
                         persisted: dict[str, Any]) -> None:
    """Run the main local agent without blocking the media sampler."""
    global main_agent_health
    descriptions = store.visual_descriptions(limit=8)
    context = build_main_agent_context(observation, persisted, window, store.list_events(limit=12)[0], store.agent_notes(limit=40), descriptions, session.scene_context)
    dedup_key = f"main_agent:{session.id}:{window['window_id']}:{settings.config_version}"
    agent_run, is_new = store.start_agent_run(agent_name="main_agent", trigger_type="multimodal_window",
                                               trigger_id=window["window_id"], window_id=window["window_id"],
                                               input_context=context, dedup_key=dedup_key)
    if not is_new and agent_run.get("status") in {"completed", "failed"}:
        return
    await emit_agent_event(agent_run["id"], stage="started", event_type="agent.analysis.started",
                           message="Main Agent started multimodal judgment",
                           payload={"window_id": window["window_id"], "model": settings.inference_model,
                                    "parallel_limit": settings.vllm_max_concurrency})
    await emit_agent_event(agent_run["id"], stage="context_built", event_type="agent.context.built",
                           message="Bounded typed context built; raw media is not stored",
                           payload={"window_id": window["window_id"], "frame_count": window.get("frame_count", 0),
                                    "audio_present": window.get("audio_present", False),
                                    "canonical_event_count": len(persisted.get("events", [])),
                                    "recognition_event_count": len(persisted.get("recognition_events", [])),
                                    "visual_description_count": len(descriptions), "scene_context_id": session.scene_context_id})
    started = time.perf_counter()
    try:
        async with vllm_semaphore:
            result = await vllm.analyze_main_agent(None, context=context)
        if result.status != "healthy":
            policy = {"policy_version": MainAgentPolicy.VERSION, "final_action": "silent", "decision": "insufficient_data",
                      "attention_level": "none", "risk_level": "unknown", "action_allowed": False,
                      "action_executed": False, "reasons": ["main agent did not return a valid judgment"],
                      "error_code": result.error_code, "window_id": window["window_id"]}
            saved = store.fail_agent_run(agent_run["id"], error_code=result.error_code or "MAIN_AGENT_UNAVAILABLE",
                                         policy=policy, latency_ms=result.latency_ms)
            main_agent_health = {"status": "degraded", "detail": {"error_code": result.error_code, "last_latency_ms": result.latency_ms}}
            await emit_agent_event(agent_run["id"], stage="failed", event_type="agent.judgment.failed",
                                   message="Main Agent returned no valid judgment; fail closed",
                                   payload={"policy": policy, "degraded": True})
            await emit_agent_event(agent_run["id"], stage="completed", event_type="agent.analysis.completed",
                                   message="Main Agent completed in degraded mode",
                                   payload={"agent_run": saved, "policy": policy, "degraded": True})
            return
        judgment = MainAgentJudgment.model_validate(result.payload["judgment"])
        await emit_agent_event(agent_run["id"], stage="judgment_ready", event_type="agent.judgment.ready",
                               message="Auditable judgment accepted from Omni",
                               payload={"situation_summary": judgment.situation_summary, "situation_phase": judgment.situation_phase,
                                        "observed_facts": judgment.observed_facts[:8], "unknowns": judgment.unknowns[:8],
                                        "hypotheses": judgment.hypotheses[:6], "proposed_action": judgment.proposed_action,
                                        "confidence": judgment.confidence})
        policy = main_agent_policy.evaluate(judgment, observation, persisted, window)
        await emit_agent_event(agent_run["id"], stage="policy_evaluated", event_type="agent.policy.evaluated",
                               message="Deterministic attention and action policy evaluated",
                               payload={"policy": policy})
        if judgment.needs_further_attention:
            focus_snapshot = media_bridge.request_focus(session, reason=judgment.attention_reason or "main_agent_requested_focus",
                                                         source_window_id=window["window_id"], context={
                                                             "main_agent_run_id": agent_run["id"],
                                                             "judgment": judgment.model_dump(),
                                                             "policy": policy,
                                                             "visual_descriptions": descriptions[:8],
                                                         })
            await emit_agent_event(agent_run["id"], stage="focus_requested", event_type="agent.focus.requested",
                                   message="Main Agent requested 2fps 10-second focus review",
                                   payload={"reason": judgment.attention_reason or "main_agent_requested_focus", "focus": focus_snapshot})
        input_hash = __import__("hashlib").sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        with db.transaction() as conn:
            call_id = store.add_model_call(conn, provider=settings.inference_provider, model=settings.inference_model, purpose="main_agent",
                                            input_hash=input_hash, prompt_version="main-agent.nemotron-omni.v1",
                                            schema_version=judgment.schema_version, status="valid", response=judgment.model_dump(),
                                            latency_ms=result.latency_ms)
        saved = store.finish_agent_run(agent_run["id"], status="completed", judgment=judgment.model_dump(), policy=policy,
                                       model_call_id=call_id, latency_ms=result.latency_ms)
        notes = []
        for note in build_main_agent_notes(judgment, policy, window, saved["id"]):
            notes.append(store.add_agent_note(**note))
        if notes:
            await emit_agent_event(agent_run["id"], stage="memory_updated", event_type="agent.memory.updated",
                                   message="Short decision and abstraction memory updated",
                                   payload={"note_ids": [note["id"] for note in notes], "layers": [note["layer"] for note in notes]})
        if judgment.segment_record and policy.get("final_action") in {"silent", "observe"} and not judgment.needs_further_attention:
            segment = store.record_time_segment(stream_id=session.id, window=window, segment=judgment.segment_record.model_dump(),
                                                description_ids=[item["id"] for item in descriptions[:8]], main_agent_run_id=saved["id"])
            await emit_agent_event(agent_run["id"], stage="segment_recorded", event_type="agent.segment.recorded",
                                   message="Quiet time segment classified from descriptions and event memory",
                                   payload={"segment": segment})
        if policy.get("final_action") != "silent":
            await emit_agent_event(agent_run["id"], stage="action_proposed", event_type="agent.action.proposed",
                                   message="Policy produced an action proposal; no executor was called",
                                   payload={"final_action": policy.get("final_action"), "action_executed": False,
                                            "attention_score": policy.get("attention_score", 0)})
        main_agent_health = {"status": "healthy", "detail": {"provider": settings.inference_provider, "model": settings.inference_model, "last_latency_ms": result.latency_ms,
                                                                 "last_action": policy["final_action"], "parallel_limit": settings.vllm_max_concurrency}}
        store.log("info", "main_agent", "Main-agent judgment accepted", context={"agent_run_id": saved["id"], "window_id": window["window_id"],
                                                                                    "final_action": policy["final_action"], "attention_level": policy["attention_level"],
                                                                                    "risk_level": policy["risk_level"], "attention_score": policy["attention_score"]})
        await emit_agent_event(agent_run["id"], stage="completed", event_type="agent.analysis.completed",
                               message="Main Agent judgment and policy completed",
                               payload={"agent_run": saved, "judgment": judgment.model_dump(), "policy": policy,
                                        "model": settings.inference_model, "provider": settings.inference_provider, "latency_ms": result.latency_ms})
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        policy = {"policy_version": MainAgentPolicy.VERSION, "final_action": "silent", "decision": "insufficient_data",
                  "attention_level": "none", "risk_level": "unknown", "action_allowed": False,
                  "action_executed": False, "reasons": ["main agent exception; fail closed"], "window_id": window["window_id"]}
        saved = store.fail_agent_run(agent_run["id"], error_code="MAIN_AGENT_EXCEPTION", policy=policy, latency_ms=elapsed)
        main_agent_health = {"status": "degraded", "detail": {"error_code": "MAIN_AGENT_EXCEPTION", "exception": type(exc).__name__}}
        store.log("error", "main_agent", "Main-agent run failed closed", context={"agent_run_id": agent_run["id"], "error": type(exc).__name__})
        await emit_agent_event(agent_run["id"], stage="completed", event_type="agent.analysis.completed",
                               message="Main Agent failed closed after exception",
                               payload={"agent_run": saved, "policy": policy, "degraded": True})


media_bridge = VirtualCameraBridge(settings, store, on_window=handle_vllm_window, on_change_gate=handle_change_gate,
                                   on_description_window=handle_detail_window,
                                   on_focus_window=handle_focus_window)


async def handle_frigate_mqtt_event(payload: dict[str, Any]) -> dict[str, Any]:
    snippet = store.record_frigate_event(frigate_event_id=payload["frigate_event_id"], camera_id=payload["camera"],
                                         update_type=payload["update_type"], label=payload["label"], zones=payload.get("zones", []),
                                         received_at=now_iso(), snapshot_uri=payload.get("snapshot_uri"), clip_uri=payload.get("clip_uri"),
                                         score=payload.get("score"), explicit_noteworthy=payload.get("noteworthy"))
    await broadcaster.send({"type": "frigate.event", "correlation_id": payload["frigate_event_id"], "payload": snippet})
    return snippet


mqtt_worker = FrigateMqttWorker(handle_frigate_mqtt_event)
frigate_health: dict[str, Any] = {"status": "disabled" if not (os.getenv("FRIGATE_BASE_URL") or settings.frigate_frame_endpoint) else "unavailable", "detail": "disabled_by_config" if not (os.getenv("FRIGATE_BASE_URL") or settings.frigate_frame_endpoint) else "not_probed"}


def service(name: str, status: str, detail: Any = None) -> dict[str, Any]:
    result = {"name": name, "status": status, "last_success_at": None}
    if detail is not None:
        result["detail"] = detail
    return result


def status_payload() -> dict[str, Any]:
    local_status = vlm_health["status"] if settings.local_vlm_mode in {"vllm", "real"} else "degraded"
    browser_capture = store.get_state("browser_capture", {}) or {}
    active_streams = media_bridge.active_snapshot()
    stream_active = bool(active_streams)
    source_status = replay.status if settings.active_source == "replay" else ("healthy" if stream_active else "starting")
    if settings.active_source == "replay" and source_status == "idle":
        source_status = "starting"
    camera_status = "healthy" if stream_active or browser_capture.get("camera_active") or settings.active_source == "replay" else "unavailable"
    microphone_status = "healthy" if stream_active or browser_capture.get("microphone_active") else "unavailable"
    if source_status not in {"healthy", "loaded", "playing", "paused"}:
        source_status = "degraded" if settings.active_source == "simulated" else "unavailable"
    source_detail = replay.snapshot() if settings.active_source == "replay" else {"source": "browser_media", "active_streams": active_streams, "vllm_sampling": settings.local_vlm_mode in {"vllm", "real"}}
    return {"app": "healthy", "environment": settings.app_env, "run_id": replay.run_id,
            "source": {"name": settings.active_source, "status": source_status, "detail": source_detail},
            "services": {
                "database": service("database", "healthy", {"path": settings.database_path, "journal_mode": "WAL"}),
                "mqtt": service("mqtt", mqtt_worker.status, mqtt_worker.error),
                "frigate_api": service("frigate_api", frigate_health["status"], {"frame_bridge_configured": bool(settings.frigate_frame_endpoint), "detail": frigate_health.get("detail")}),
                "camera": service("camera", camera_status, {"mode": settings.active_source, "browser_capture": browser_capture}),
                "virtual_camera": service("virtual_camera", "healthy" if stream_active else "starting", {"active_streams": active_streams, "rtsp_publish_configured": bool(settings.frigate_rtsp_publish_url)}),
                "apple_detector": service("apple_detector", "unavailable", "macOS host detector not configured"),
                "microphone": service("microphone", microphone_status, browser_capture if microphone_status == "healthy" else "browser microphone not active"),
                "vad": service("vad", "unavailable", "Silero runtime not configured"),
                "whisper": service("whisper", "unavailable", settings.whisper_model),
                "local_vlm": service("local_vlm", local_status, {"provider": settings.inference_provider, "mode": settings.local_vlm_mode, "model": settings.inference_model if settings.local_vlm_mode in {"vllm", "real"} else settings.local_vlm_model, "endpoint": settings.inference_base_url if settings.local_vlm_mode in {"vllm", "real"} else None, "quantization": settings.local_vlm_quantization, "change_gate": {"method": "local_pixel_delta_plus_audio", "threshold": settings.change_gate_threshold, "audio_delta_threshold": settings.change_gate_audio_delta_threshold, "min_changed_pairs": settings.change_gate_min_changed_pairs, "strong_score_multiplier": settings.change_gate_strong_score_multiplier, "model_calls": 0, "thinking": False}, "thinking": {"change_gate": False, "observation": settings.vllm_observation_enable_thinking, "main_agent": settings.vllm_main_agent_enable_thinking}, "sampling": {"fps": settings.vllm_sample_fps, "window_seconds": settings.vllm_window_seconds, "window_stride_seconds": settings.vllm_window_stride_seconds, "frames_per_window": settings.vllm_window_frames, "max_concurrency": settings.vllm_max_concurrency, "max_pending_windows": settings.vllm_max_pending_windows}, "detail_sampling": {"fps": settings.detail_sample_fps, "window_seconds": settings.detail_window_seconds, "window_frames": settings.detail_window_frames, "active_seconds": settings.detail_active_seconds}, "focus_sampling": {"fps": settings.vllm_sample_fps, "window_seconds": settings.focus_window_seconds, "window_frames": settings.focus_window_frames}, "detail": vlm_health.get("detail")}),
                "main_agent": service("main_agent", main_agent_health["status"], main_agent_health.get("detail") | {"provider": settings.inference_provider, "enabled": settings.main_agent_enabled, "pending": len(main_agent_tasks), "max_pending": settings.main_agent_max_pending, "parallel_limit": settings.vllm_max_concurrency, "interval_seconds": settings.main_agent_interval_seconds} if isinstance(main_agent_health.get("detail"), dict) else {"provider": settings.inference_provider, "enabled": settings.main_agent_enabled, "pending": len(main_agent_tasks), "max_pending": settings.main_agent_max_pending, "parallel_limit": settings.vllm_max_concurrency, "interval_seconds": settings.main_agent_interval_seconds, "detail": main_agent_health.get("detail")}),
                "minimax": service("minimax", minimax_health["status"], minimax_health.get("detail") | {"configured": settings.minimax_configured, "model": settings.minimax_model} if isinstance(minimax_health.get("detail"), dict) else {"configured": settings.minimax_configured, "model": settings.minimax_model, "detail": minimax_health.get("detail")}),
                "telegram": service("telegram", "healthy" if settings.telegram_configured else "unavailable", {"configured": settings.telegram_configured}),
                "model_store": service("model_store", "healthy", {"path": str(Path("data/models"))}),
                "scheduler": service("scheduler", "healthy", {"observer": "manual_or_daily"}),
            }}


def window_range(window: str) -> tuple[str, str]:
    if window not in {"1h", "6h", "24h", "7d", "30d"}:
        raise HTTPException(422, detail={"error": {"code": "INVALID_WINDOW", "message": "window must be one of 1h, 6h, 24h, 7d, 30d", "retryable": False}})
    end = datetime.now(timezone.utc)
    amount = {"1h": timedelta(hours=1), "6h": timedelta(hours=6), "24h": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}[window]
    return (end - amount).isoformat(), end.isoformat()


def record_job(job_id: str, status: str, **fields: Any) -> None:
    jobs.setdefault(job_id, {}).update({"job_id": job_id, "status": status, "updated_at": now_iso(), **fields})


async def emit_agent_event(agent_run_id: str, *, stage: str, event_type: str,
                           message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = store.add_agent_run_event(agent_run_id, stage=stage, event_type=event_type, message=message, payload=payload)
    await broadcaster.send({"type": event_type, "correlation_id": agent_run_id,
                            "payload": {"agent_run_id": agent_run_id, "stage": stage, "message": message,
                                        "event": event, **(payload or {})}})
    return event


async def run_analysis(job_id: str, window: str, force: bool = False) -> None:
    start, end = window_range(window)
    record_job(job_id, "running", window=window)
    await broadcaster.send({"type": "cloud_analysis.started", "correlation_id": job_id, "payload": {"job_id": job_id, "window": window}})
    snapshot = store.health_snapshot(lookback_minutes={"1h": 60, "6h": 360, "24h": 1440, "7d": 10080, "30d": 43200}[window])
    event_summary = store.event_summary(start, end)
    summary = {"subject_id": settings.subject_id, "window": {"start": start, "end": end}, "health_snapshot": snapshot,
               "event_summary": event_summary, "data_limitations": ["health values are simulated", "hydration volume is estimated"]}
    store.record_tool_call("health_context", "get_health_snapshot", {"subject_id": settings.subject_id, "at": end, "lookback_minutes": {"1h": 60, "6h": 360, "24h": 1440, "7d": 10080, "30d": 43200}[window]}, snapshot)
    store.record_tool_call("health_context", "get_event_counts", {"subject_id": settings.subject_id, "event_types": ["fall", "hydration"], "start": start, "end": end}, event_summary)
    store.record_tool_call("health_context", "get_hydration_summary", {"subject_id": settings.subject_id, "start": start, "end": end}, event_summary["hydration"])
    adapter_result = await minimax.analyze(summary, window)
    result = adapter_result.payload
    if adapter_result.status == "invalid":
        result = result.get("fallback", MiniMaxAdapter._local_result(summary, window))
    call_id = None
    with db.transaction() as conn:
        call_id = store.add_model_call(conn, provider="minimax", model=settings.minimax_model, purpose="health_risk",
                                        input_hash=__import__("hashlib").sha256(json.dumps(summary, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                                        prompt_version="health-risk.v1", schema_version="health-risk.v1", status=adapter_result.status,
                                        response=result, latency_ms=adapter_result.latency_ms, error_code=adapter_result.error_code)
    analysis = store.add_analysis(summary, result, start, end, call_id, result.get("risk_level", "unknown"))
    record_job(job_id, "completed", analysis_id=analysis["id"], degraded=bool(result.get("degraded", adapter_result.status != "healthy")), result=result)
    await broadcaster.send({"type": "cloud_analysis.completed", "correlation_id": job_id, "payload": {"job_id": job_id, "analysis": analysis, "degraded": jobs[job_id].get("degraded", False)}})


async def notify_for_action(action: dict[str, Any]) -> None:
    if not settings.telegram_configured or action.get("action_type") != "dashboard_alert":
        return
    event_id = action.get("event_id")
    for chat_id in settings.telegram_allowed_chat_ids:
        delivery_key = f"{action['id']}:{chat_id}:telegram"
        existing = db.fetch_one("SELECT * FROM notification_deliveries WHERE idempotency_key=?", (delivery_key,))
        if existing:
            continue
        delivery_id = make_id("delivery")
        ts = now_iso()
        with db.transaction() as conn:
            conn.execute("INSERT INTO notification_deliveries(id,action_id,channel,recipient_ref,status,attempt_count,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (delivery_id, action["id"], "telegram", chat_id, "sending", 1, delivery_key, ts, ts))
        text = f"照護警報：事件 {event_id} 尚未觀察到恢復。請確認長輩狀況。Dashboard event: {event_id}"
        result = await telegram.send(text, delivery_id, chat_id)
        with db.transaction() as conn:
            if result.status == "sent":
                conn.execute("UPDATE notification_deliveries SET status='sent',provider_message_id=?,sent_at=?,updated_at=? WHERE id=?", (result.payload.get("provider_message_id"), now_iso(), now_iso(), delivery_id))
            else:
                conn.execute("UPDATE notification_deliveries SET status='failed',last_error_code=?,updated_at=? WHERE id=?", (result.error_code, now_iso(), delivery_id))
        await broadcaster.send({"type": "notification.updated", "correlation_id": delivery_id, "payload": db.fetch_one("SELECT * FROM notification_deliveries WHERE id=?", (delivery_id,))})


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    Path(settings.media_root).mkdir(parents=True, exist_ok=True)
    # Restore only non-secret settings. Secret values intentionally remain in
    # environment/process memory and are never persisted in SQLite.
    for saved in db.fetch_all("SELECT key,value_json,config_version FROM settings"):
        if saved["key"] in {"minimax_api_key", "telegram_bot_token"}:
            continue
        try:
            value = json.loads(saved["value_json"])
            if saved["key"] == "telegram_allowed_chat_ids":
                value = tuple(value)
            if hasattr(settings, saved["key"]):
                setattr(settings, saved["key"], value)
            settings.config_version = saved["config_version"] or settings.config_version
        except (TypeError, ValueError, json.JSONDecodeError):
            store.log("warning", "settings", "Ignored invalid persisted setting", context={"key": saved["key"]})
    with db.transaction() as conn:
        for item in ReplayManager.catalog():
            conn.execute("INSERT OR IGNORE INTO replay_sources(id,display_name,event_type,duration_ms,source_uri,allowlisted) VALUES(?,?,?,?,?,1)",
                         (item["id"], item["display_name"], item["event_type"], item["duration_ms"], f"synthetic://{item['id']}"))
    mqtt_worker.start(asyncio.get_running_loop())
    if settings.local_vlm_mode in {"vllm", "real"}:
        vlm_probe = await vllm.probe()
        vlm_health.update({"status": vlm_probe.status, "detail": vlm_probe.payload | ({"error_code": vlm_probe.error_code} if vlm_probe.error_code else {})})
        if settings.main_agent_enabled:
            main_agent_health.update({"status": "starting" if vlm_probe.status == "healthy" else "degraded",
                                      "detail": {"provider": settings.inference_provider, "model": settings.inference_model, "vllm_status": vlm_probe.status,
                                                 "parallel_limit": settings.vllm_max_concurrency}})
    if settings.minimax_configured:
        minimax_probe = await minimax.probe()
        minimax_health.update({"status": minimax_probe.status, "detail": minimax_probe.payload | ({"error_code": minimax_probe.error_code} if minimax_probe.error_code else {})})
    if os.getenv("FRIGATE_BASE_URL") or settings.frigate_frame_endpoint:
        probe = await frigate.test()
        frigate_health.update({"status": probe.status, "detail": probe.payload | ({"error_code": probe.error_code} if probe.error_code else {})})
    store.log("info", "backend", "Care Agent backend started", context={"source": settings.active_source, "mode": settings.demo_mode})
    yield
    await replay.pause()
    for task in list(main_agent_tasks):
        task.cancel()
    if main_agent_tasks:
        await asyncio.gather(*main_agent_tasks, return_exceptions=True)
    main_agent_tasks.clear()
    mqtt_worker.stop()


app = FastAPI(title="Care Agent OS", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin, "http://localhost:5173"], allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?::\d+)?$", allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": {"code": "HTTP_ERROR", "message": str(exc.detail), "retryable": False}}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.get("/api/status")
async def api_status():
    return status_payload()


@app.get("/api/cameras")
async def cameras():
    camera = status_payload()["services"]["camera"]
    latest = store.frigate_logs(False, 1)
    return {"items": [{"id": "demo-camera", "name": "Demo camera", "source": settings.active_source, "status": camera["status"], "last_frame_at": latest[0]["received_at"] if latest else (now_iso() if replay.position_ms else None), "recent_frame": latest[0] if latest else None}]}


@app.post("/api/capture/status")
async def capture_status(request: CaptureStatusRequest):
    payload = request.model_dump() | {"updated_at": now_iso(), "source": "browser_getUserMedia"}
    store.set_state("browser_capture", payload)
    await broadcaster.send({"type": "camera.status", "payload": {"capture": payload, "services": status_payload()["services"]}})
    return payload


@app.post("/api/frigate/frames")
async def frigate_frame(frame: UploadFile = File(...), camera_id: str = Form("browser-camera")):
    """Validate a browser frame, assess it through the configured Frigate bridge, and discard raw pixels."""
    content_type = (frame.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, detail={"error": {"code": "UNSUPPORTED_FRAME_TYPE", "message": "camera frame must be JPEG, PNG, or WebP", "retryable": False}})
    body = await frame.read(5_242_881)
    if len(body) > 5_242_880:
        raise HTTPException(413, detail={"error": {"code": "FRAME_TOO_LARGE", "message": "camera frame exceeds 5 MB", "retryable": False}})
    try:
        from PIL import Image
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
            width, height = image.size
    except Exception:
        raise HTTPException(400, detail={"error": {"code": "INVALID_IMAGE", "message": "uploaded camera frame is not a valid image", "retryable": False}})
    assessment = await frigate.assess_frame(body, camera_id, content_type)
    detections = assessment.payload.get("detections", [])
    explicit = assessment.payload.get("noteworthy") if isinstance(assessment.payload.get("noteworthy"), bool) else None
    reason_override = None if assessment.status == "healthy" else assessment.payload.get("message") or assessment.error_code
    snippet = store.record_frame_log(camera_id=camera_id, received_at=now_iso(), frame_sha256=hashlib.sha256(body).hexdigest(), width=width, height=height,
                                     detections=detections, decision_source=assessment.payload.get("decision_source", "frigate_frame_bridge"),
                                     explicit_noteworthy=explicit, reason_override=reason_override)
    await broadcaster.send({"type": "frigate.event", "correlation_id": snippet["id"], "payload": snippet})
    return {"status": assessment.status, "snippet": snippet, "raw_frame_persisted": False, "adapter_error": assessment.error_code}


@app.get("/api/frigate/logs")
async def frigate_logs(noteworthy_only: bool = True, limit: int = Query(50, ge=1, le=200)):
    return {"items": store.frigate_logs(noteworthy_only, limit), "noteworthy_only": noteworthy_only}


@app.get("/api/recognition/logs")
async def recognition_logs(limit: int = Query(50, ge=1, le=200)):
    return {"items": store.recognition_logs(limit), "source": "local_vllm_plus_frigate_if_enabled"}


@app.get("/api/agent/runs")
async def agent_runs(limit: int = Query(30, ge=1, le=100)):
    return {"items": store.agent_runs(limit), "agent": "main_agent", "provider": settings.inference_provider, "model": settings.inference_model}


@app.get("/api/agent/events")
async def agent_events(limit: int = Query(100, ge=1, le=300)):
    return {"items": store.agent_run_events(limit)}


@app.get("/api/agent/notes")
async def agent_notes(layer: str | None = Query(None, pattern="^(decision|abstraction|research)$"), limit: int = Query(100, ge=1, le=300)):
    return {"items": store.agent_notes(layer=layer, limit=limit)}


@app.post("/api/sources/activate")
async def activate_source(request: SourceActivateRequest):
    settings.active_source = request.source
    if request.source != "replay":
        replay.status = "idle"
    await broadcaster.send({"type": "camera.status", "payload": status_payload()["source"]})
    return {"source": request.source, "status": status_payload()["source"]}


@app.get("/api/events")
async def events(event_type: str | None = Query(None, alias="type"), status: str | None = None, start: str | None = None, end: str | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    items, total = store.list_events(event_type, status, start, end, page_size, (page - 1) * page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/events/{event_id}")
async def event_detail(event_id: str):
    result = store.event_detail(event_id)
    if not result:
        raise HTTPException(404, detail={"error": {"code": "EVENT_NOT_FOUND", "message": "event not found", "retryable": False}})
    return result


@app.get("/api/hydration/summary")
async def hydration_summary(start: str | None = None, end: str | None = None):
    if not start or not end:
        end = now_iso(); start = (datetime.now(timezone.utc).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)).astimezone(timezone.utc).isoformat()
    return store.hydration_summary(start, end) | {"window": {"start": start, "end": end}, "estimated": True}


@app.get("/api/health/current")
async def health_current():
    return store.health_snapshot()


@app.post("/api/health/scenario")
async def health_scenario(request: HealthScenarioRequest):
    snapshot = store.add_health_scenario(request.scenario)
    await broadcaster.send({"type": "health.updated", "payload": snapshot})
    return snapshot


@app.post("/api/health/analyze", status_code=202)
async def health_analyze(request: WindowRequest):
    job_id = make_id("job")
    record_job(job_id, "queued", kind="health_analysis", window=request.window)
    asyncio.create_task(run_analysis(job_id, request.window, request.force))
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/events/{event_id}/analyze", status_code=202)
async def event_analyze(event_id: str):
    event = store.event_detail(event_id)
    if not event:
        raise HTTPException(404, detail={"error": {"code": "EVENT_NOT_FOUND", "message": "event not found", "retryable": False}})
    job_id = make_id("job")
    record_job(job_id, "completed", kind="event_understanding", event_id=event_id,
               result={"summary_zh_tw": "已建立事件理解摘要，仍需依照護流程人工確認。", "supporting_evidence": event.get("evidence", []), "uncertainty": ["此為輔助觀察，不是診斷"]})
    await broadcaster.send({"type": "local_analysis.completed", "correlation_id": job_id, "payload": jobs[job_id]})
    return {"job_id": job_id, "status": "completed", "result": jobs[job_id]["result"]}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, detail={"error": {"code": "JOB_NOT_FOUND", "message": "job not found", "retryable": False}})
    return jobs[job_id]


@app.get("/api/replay/catalog")
async def replay_catalog():
    return {"items": ReplayManager.catalog()}


@app.post("/api/replay/load")
async def replay_load(request: ReplayLoadRequest):
    try:
        return await replay.load(request.video_id)
    except ValueError as exc:
        raise HTTPException(422, detail={"error": {"code": "REPLAY_NOT_ALLOWLISTED", "message": str(exc), "retryable": False}})


@app.post("/api/replay/start")
async def replay_start():
    try:
        return await replay.start()
    except ValueError as exc:
        raise HTTPException(409, detail={"error": {"code": "REPLAY_NOT_LOADED", "message": str(exc), "retryable": False}})


@app.post("/api/replay/pause")
async def replay_pause():
    return await replay.pause()


@app.post("/api/replay/reset")
async def replay_reset():
    return await replay.reset()


async def _reset_history() -> dict[str, Any]:
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(403, detail={"error": {"code": "DEV_ONLY", "message": "demo reset is available only in development", "retryable": False}})
    await replay.reset()
    active_stream_ids = [item["stream_id"] for item in media_bridge.active_snapshot()]
    with db.transaction() as conn:
        # Respect the FK graph so a reset is deterministic even after an alert,
        # analysis, transcript, and Telegram delivery were all created.
        # Delete children before their referenced event/model rows. In
        # particular visual_descriptions/focus_reviews/scene_contexts reference
        # model_calls, so model_calls must be deleted near the end.
        for table in ("notification_deliveries", "event_evidence", "hydration_sessions", "tool_calls", "transcripts", "actions", "focus_reviews", "visual_descriptions", "scene_contexts", "agent_run_events", "agent_notes", "analyses", "agent_runs", "memories", "recognition_events", "events", "evidence", "model_calls", "health_samples", "daily_summaries", "observer_findings", "frigate_log_snippets", "time_segments", "change_gate_results", "app_logs"):
            conn.execute(f"DELETE FROM {table}")
        if active_stream_ids:
            placeholders = ",".join("?" for _ in active_stream_ids)
            conn.execute(f"DELETE FROM virtual_camera_streams WHERE id NOT IN ({placeholders})", tuple(active_stream_ids))
        else:
            conn.execute("DELETE FROM virtual_camera_streams")
    store.clear_runtime()
    media_bridge.reset_analysis_state()
    await broadcaster.send({"type": "history.reset", "payload": {"message": "History reset complete", "run_id": replay.run_id,
                                                                    "active_streams_preserved": len(active_stream_ids)}})
    return {"ok": True, "run_id": replay.run_id, "active_streams_preserved": len(active_stream_ids),
            "preserved": ["settings", "model_installations", "model_download_jobs"]}


@app.post("/api/history/reset")
async def history_reset():
    return await _reset_history()


@app.post("/api/demo/reset")
async def demo_reset():
    return await _reset_history()


@app.get("/api/transcripts/recent")
async def transcripts_recent():
    return {"items": store.recent_transcripts(), "retention_minutes": settings.transcript_retention_minutes}


@app.post("/api/audio/transcript")
async def add_transcript(request: AudioTranscriptRequest):
    transcript = store.add_transcript(request.text, request.started_at or datetime.now(timezone.utc), request.duration_sec, request.confidence)
    await broadcaster.send({"type": "audio.transcript", "payload": transcript})
    return transcript


@app.post("/api/audio/vad")
async def vad_activity(request: VadActivityRequest):
    occurred_at = (request.occurred_at or datetime.now(timezone.utc)).isoformat()
    payload = {"segment_id": request.segment_id, "active": request.active, "probability": request.probability, "occurred_at": occurred_at,
               "mode": "adapter_input", "privacy": "transcript is only created by explicit audio transcript endpoint"}
    await broadcaster.send({"type": "audio.vad", "payload": payload})
    return payload


@app.post("/api/frigate/events")
async def frigate_event(request: FrigateEventRequest):
    """Normalize a Frigate lifecycle event without coupling downstream code to Frigate JSON."""
    payload = {"event_id": request.frigate_event_id, "camera": request.camera, "label": request.label,
               "update_type": request.update_type, "zones": request.zones,
               "start_time": request.started_at.isoformat(), "end_time": request.ended_at.isoformat() if request.ended_at else None,
               "snapshot_available": bool(request.snapshot_uri), "clip_available": bool(request.clip_uri), "score": request.score,
               "source_contract": "EventCandidate.v1"}
    snippet = store.record_frigate_event(frigate_event_id=request.frigate_event_id, camera_id=request.camera,
                                         update_type=request.update_type, label=request.label, zones=request.zones,
                                         received_at=now_iso(), snapshot_uri=request.snapshot_uri, clip_uri=request.clip_uri,
                                         score=request.score, explicit_noteworthy=request.noteworthy)
    payload["noteworthy"] = bool(snippet["noteworthy"])
    payload["log_snippet"] = snippet["log_excerpt"]
    await broadcaster.send({"type": "frigate.event", "correlation_id": request.frigate_event_id, "payload": payload})
    return payload


@app.get("/api/tools/calls")
async def tools_calls(limit: int = Query(100, ge=1, le=500)):
    return {"items": store.tool_calls(limit)}


@app.get("/api/logs")
async def api_logs(limit: int = Query(100, ge=1, le=500)):
    return {"items": store.logs(limit)}


@app.get("/api/observer/findings")
async def observer_findings():
    return {"items": store.list_findings()}


@app.post("/api/observer/run")
async def observer_run():
    result = await asyncio.to_thread(store.observer_run)
    if result.get("finding"):
        await broadcaster.send({"type": "observer.finding", "payload": result["finding"]})
    return {"summary_count": len(result["summaries"]), "finding": result.get("finding"), "baseline": result["baseline"]}


@app.post("/api/observer/seed")
async def observer_seed(days: int = Query(30, ge=1, le=90)):
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(403, detail={"error": {"code": "DEV_ONLY", "message": "observer seed is available only in development", "retryable": False}})
    return store.seed_history(days)


@app.get("/api/notifications")
async def notifications():
    return {"items": db.fetch_all("SELECT * FROM notification_deliveries ORDER BY created_at DESC LIMIT 100")}


@app.post("/api/notifications/test")
async def notification_test():
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(403, detail={"error": {"code": "DEV_ONLY", "message": "notification test is available only in development", "retryable": False}})
    result = await telegram.test()
    if result.status != "healthy":
        raise HTTPException(503, detail={"error": {"code": result.error_code or "TELEGRAM_UNAVAILABLE", "message": "Telegram is not configured or reachable", "retryable": True}})
    return result.payload


@app.post("/api/notifications/{delivery_id}/ack")
async def notification_ack(delivery_id: str, false_alarm: bool = False, acknowledged_by: str = "dashboard"):
    current = db.fetch_one("SELECT * FROM notification_deliveries WHERE id=?", (delivery_id,))
    if not current:
        raise HTTPException(404, detail={"error": {"code": "DELIVERY_NOT_FOUND", "message": "delivery not found", "retryable": False}})
    status = "false_alarm" if false_alarm else "acknowledged"
    with db.transaction() as conn:
        conn.execute("UPDATE notification_deliveries SET status=?,acknowledged_at=?,acknowledged_by=?,acknowledgement_type=?,updated_at=? WHERE id=? AND status='sent'",
                     (status, now_iso(), acknowledged_by, status, now_iso(), delivery_id))
    updated = db.fetch_one("SELECT * FROM notification_deliveries WHERE id=?", (delivery_id,))
    await broadcaster.send({"type": "notification.updated", "correlation_id": delivery_id, "payload": updated})
    return updated


@app.get("/api/setup/status")
async def setup_status():
    return store.setup_status() | {"prerequisites": await prerequisites()}


async def prerequisites() -> dict[str, Any]:
    usage = shutil.disk_usage(Path(settings.database_path).parent if Path(settings.database_path).parent.exists() else Path("."))
    return {"python": {"version": platform.python_version(), "ok": platform.python_version_tuple() >= ("3", "10", "0")},
            "platform": platform.platform(), "memory": {"available_bytes": None, "note": "platform-specific check not exposed"},
            "disk": {"free_bytes": usage.free, "ok": usage.free > 1_000_000_000}, "docker": {"ok": bool(os.getenv("FRIGATE_BASE_URL")), "note": "optional for replay mode"}}


@app.get("/api/setup/prerequisites")
async def setup_prerequisites():
    return await prerequisites()


@app.post("/api/setup/complete")
async def setup_complete():
    store.set_state("setup_completed", True)
    await broadcaster.send({"type": "setup.updated", "payload": await setup_status()})
    return await setup_status()


@app.get("/api/models/catalog")
async def models_catalog():
    return {"items": [
        {"id": "Qwen3-VL-8B-Instruct", "display_name": "Qwen3-VL 8B Instruct", "provider": "local", "revision": "configured-at-runtime", "modality": "vision", "quantization": ["4bit"], "estimated_size_bytes": 5_500_000_000, "minimum_memory_bytes": 8_000_000_000, "recommended_memory_bytes": 12_000_000_000, "runtime": "mlx-vlm", "source_allowlist": ["huggingface.co"], "expected_files": ["config.json", "*.safetensors"]},
        {"id": "Qwen3-VL-4B-Instruct", "display_name": "Qwen3-VL 4B Instruct (fallback)", "provider": "local", "revision": "configured-at-runtime", "modality": "vision", "quantization": ["4bit"], "estimated_size_bytes": 3_000_000_000, "minimum_memory_bytes": 5_000_000_000, "recommended_memory_bytes": 8_000_000_000, "runtime": "mlx-vlm", "source_allowlist": ["huggingface.co"], "expected_files": ["config.json", "*.safetensors"]},
        {"id": "whisper-small", "display_name": "Whisper small (Chinese)", "provider": "local", "revision": "configured-at-runtime", "modality": "audio", "quantization": ["4bit"], "estimated_size_bytes": 500_000_000, "minimum_memory_bytes": 1_000_000_000, "recommended_memory_bytes": 2_000_000_000, "runtime": "mlx-whisper", "source_allowlist": ["huggingface.co"], "expected_files": ["config.json"]},
    ]}


@app.get("/api/models/installed")
async def models_installed():
    rows = db.fetch_all("SELECT * FROM model_installations ORDER BY created_at DESC")
    return {"items": rows}


@app.post("/api/models/downloads", status_code=202)
async def model_download(request: ModelDownloadRequest):
    catalog = (await models_catalog())["items"]
    item = next((x for x in catalog if x["id"] == request.model_id), None)
    if not item:
        raise HTTPException(422, detail={"error": {"code": "MODEL_NOT_ALLOWLISTED", "message": "model_id is not in backend catalog", "retryable": False}})
    job_id = make_id("download")
    ts = now_iso()
    with db.transaction() as conn:
        conn.execute("INSERT INTO model_download_jobs(id,model_id,quantization,status,progress,bytes_done,bytes_total,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (job_id, request.model_id, request.quantization, "queued", 0, 0, item["estimated_size_bytes"], ts, ts))
    record_job(job_id, "queued", kind="model_download", model_id=request.model_id, quantization=request.quantization)
    asyncio.create_task(simulate_model_download(job_id, item, request.quantization))
    return {"job_id": job_id, "status": "queued"}


async def simulate_model_download(job_id: str, item: dict, quantization: str) -> None:
    # The Windows/dev fallback never downloads from an arbitrary URL. A real deployment
    # replaces this bounded task with the allowlisted Hugging Face downloader.
    if os.getenv("MODEL_DOWNLOAD_MODE", "stub") != "stub":
        record_job(job_id, "failed", error_code="MODEL_DOWNLOADER_NOT_CONFIGURED")
        with db.transaction() as conn:
            conn.execute("UPDATE model_download_jobs SET status='failed',error_code=?,updated_at=? WHERE id=?", ("MODEL_DOWNLOADER_NOT_CONFIGURED", now_iso(), job_id))
        return
    for progress in (10, 30, 55, 80, 100):
        await asyncio.sleep(0.05)
        done = int(item["estimated_size_bytes"] * progress / 100)
        with db.transaction() as conn:
            conn.execute("UPDATE model_download_jobs SET status=?,progress=?,bytes_done=?,updated_at=? WHERE id=?", ("completed" if progress == 100 else "downloading", progress, done, now_iso(), job_id))
        record_job(job_id, "completed" if progress == 100 else "running", progress=progress, bytes_done=done, bytes_total=item["estimated_size_bytes"])
        await broadcaster.send({"type": "model.download.progress", "correlation_id": job_id, "payload": jobs[job_id]})
    install_id = make_id("model")
    with db.transaction() as conn:
        conn.execute("INSERT INTO model_installations(id,model_id,quantization,revision,status,bytes,path,is_active,installed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (install_id, item["id"], quantization, item["revision"], "installed_stub", item["estimated_size_bytes"], "data/models/" + item["id"], 0, now_iso(), now_iso()))


@app.get("/api/models/downloads/{job_id}")
async def model_download_status(job_id: str):
    row = db.fetch_one("SELECT * FROM model_download_jobs WHERE id=?", (job_id,))
    if not row:
        raise HTTPException(404, detail={"error": {"code": "DOWNLOAD_NOT_FOUND", "message": "download job not found", "retryable": False}})
    return row | jobs.get(job_id, {})


@app.delete("/api/models/downloads/{job_id}")
async def model_download_cancel(job_id: str):
    if not db.fetch_one("SELECT id FROM model_download_jobs WHERE id=?", (job_id,)):
        raise HTTPException(404, detail={"error": {"code": "DOWNLOAD_NOT_FOUND", "message": "download job not found", "retryable": False}})
    with db.transaction() as conn:
        conn.execute("UPDATE model_download_jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','downloading')", (now_iso(), job_id))
    record_job(job_id, "cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@app.post("/api/models/{model_id}/activate")
async def model_activate(model_id: str):
    row = db.fetch_one("SELECT * FROM model_installations WHERE model_id=? AND status='installed_stub' ORDER BY created_at DESC LIMIT 1", (model_id,))
    if not row:
        raise HTTPException(409, detail={"error": {"code": "MODEL_NOT_INSTALLED", "message": "model must pass the download/load probe first", "retryable": False}})
    with db.transaction() as conn:
        conn.execute("UPDATE model_installations SET is_active=0 WHERE is_active=1")
        conn.execute("UPDATE model_installations SET is_active=1,status='active' WHERE id=?", (row["id"],))
    settings.local_vlm_model = model_id
    settings.local_vlm_mode = "stub" if os.getenv("LOCAL_VLM_MODE", "stub") == "stub" else "real"
    await broadcaster.send({"type": "model.activated", "payload": {"model_id": model_id, "mode": settings.local_vlm_mode, "revision": row["revision"]}})
    return {"model_id": model_id, "mode": settings.local_vlm_mode, "revision": row["revision"]}


@app.post("/api/integrations/frigate/test")
async def frigate_test():
    result = await frigate.test()
    frigate_health.update({"status": result.status, "detail": result.payload | ({"error_code": result.error_code} if result.error_code else {})})
    return {"status": result.status, "details": result.payload, "error_code": result.error_code}


@app.post("/api/integrations/minimax/test")
async def minimax_test():
    result = await minimax.probe()
    minimax_health.update({"status": result.status, "detail": result.payload | ({"error_code": result.error_code} if result.error_code else {})})
    return {"status": result.status, "details": result.payload, "error_code": result.error_code}


@app.post("/api/integrations/vllm/test")
async def vllm_test():
    result = await vllm.probe()
    vlm_health.update({"status": result.status, "detail": result.payload | ({"error_code": result.error_code} if result.error_code else {})})
    return {"status": result.status, "details": result.payload, "error_code": result.error_code}


@app.post("/api/integrations/telegram/test")
async def telegram_test():
    result = await telegram.test()
    return {"status": result.status, "details": result.payload, "error_code": result.error_code}


@app.get("/api/settings")
async def get_settings_api():
    return {"config_version": settings.config_version, "demo_mode": settings.demo_mode, "active_source": settings.active_source,
            "local_vlm_model": settings.local_vlm_model, "local_vlm_quantization": settings.local_vlm_quantization, "whisper_model": settings.whisper_model,
            "local_vlm_mode": settings.local_vlm_mode, "vllm_base_url": settings.vllm_base_url, "vllm_model": settings.vllm_model,
            "flow_model_provider": settings.inference_provider, "flow_model_base_url": settings.inference_base_url, "flow_model_id": settings.inference_model,
            "vllm_sample_fps": settings.vllm_sample_fps, "vllm_window_seconds": settings.vllm_window_seconds, "vllm_window_stride_seconds": settings.vllm_window_stride_seconds, "vllm_window_frames": settings.vllm_window_frames,
            "hydration_target_ml": settings.hydration_target_ml, "estimated_ml_per_session": settings.estimated_ml_per_session,
            "fall_confirm_window_sec": settings.fall_confirm_window_sec, "fall_no_recovery_alert_sec": settings.fall_no_recovery_alert_sec,
            "demo_no_recovery_alert_sec": settings.demo_no_recovery_alert_sec, "minimax_model": settings.minimax_model,
            "minimax_base_url": settings.minimax_base_url, "minimax_api_key_configured": settings.minimax_configured,
            "telegram_token_configured": bool(settings.telegram_bot_token), "telegram_allowed_chat_ids_configured": bool(settings.telegram_allowed_chat_ids)}


@app.patch("/api/settings")
async def patch_settings(request: SetupSettingsPatch):
    values = request.model_dump(exclude_none=True)
    secret_fields = {"minimax_api_key", "telegram_bot_token"}
    for key, value in values.items():
        if key in secret_fields:
            setattr(settings, key, value)
        elif key == "telegram_allowed_chat_ids":
            settings.telegram_allowed_chat_ids = tuple(value)
        elif hasattr(settings, key):
            setattr(settings, key, value)
    settings.config_version = f"config.{int(time.time())}"
    with db.transaction() as conn:
        for key, value in values.items():
            if key in secret_fields:
                continue
            persisted = list(value) if key == "telegram_allowed_chat_ids" else value
            conn.execute("INSERT INTO settings(key,value_json,config_version,updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,config_version=excluded.config_version,updated_at=excluded.updated_at",
                         (key, db.dumps(persisted), settings.config_version, now_iso()))
    await broadcaster.send({"type": "setup.updated", "payload": await get_settings_api()})
    return await get_settings_api()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong", "occurred_at": now_iso(), "schema_version": "realtime.v1"})
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)


@app.websocket("/ws/media")
async def media_websocket(websocket: WebSocket, camera_id: str = Query("browser-camera", min_length=1, max_length=100), media_type: str = Query("video/webm", min_length=5, max_length=100)):
    """Ingest a continuous MediaRecorder WebM stream, never a screenshot sequence."""
    if not settings.virtual_camera_enabled:
        await websocket.close(code=1008, reason="virtual camera is disabled")
        return
    await websocket.accept()
    session = await media_bridge.open(camera_id, media_type)
    store.set_state("browser_capture", {"camera_active": True, "microphone_active": True, "stream_active": True, "stream_id": session.id, "updated_at": now_iso(), "source": "browser_media_recorder"})
    last_progress = time.monotonic()
    await websocket.send_json({"type": "media.stream.ready", "payload": media_bridge.snapshot(session), "schema_version": "media-stream.v1"})
    await broadcaster.send({"type": "camera.status", "payload": status_payload()["services"]["virtual_camera"]})
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            chunk = message.get("bytes")
            if chunk is not None:
                await media_bridge.receive(session, chunk)
                if time.monotonic() - last_progress >= 1:
                    last_progress = time.monotonic()
                    await websocket.send_json({"type": "media.stream.progress", "payload": media_bridge.snapshot(session), "schema_version": "media-stream.v1"})
            elif message.get("text") == "ping":
                await websocket.send_json({"type": "pong", "schema_version": "media-stream.v1"})
    except WebSocketDisconnect:
        pass
    finally:
        await media_bridge.close(session)
        store.set_state("browser_capture", {"camera_active": False, "microphone_active": False, "stream_active": False, "updated_at": now_iso(), "source": "browser_media_recorder"})
        await broadcaster.send({"type": "camera.status", "payload": status_payload()["services"]["virtual_camera"]})


@app.get("/api/media/streams")
async def media_streams():
    return {"active": media_bridge.active_snapshot(), "recent": db.fetch_all("SELECT * FROM virtual_camera_streams ORDER BY started_at DESC LIMIT 20")}


@app.get("/api/media/scene-contexts")
async def media_scene_contexts(limit: int = Query(20, ge=1, le=100)):
    return {"items": store.scene_contexts(limit)}


@app.get("/api/media/descriptions")
async def media_descriptions(limit: int = Query(50, ge=1, le=200)):
    return {"items": store.visual_descriptions(limit)}


@app.get("/api/media/focus-reviews")
async def media_focus_reviews(limit: int = Query(50, ge=1, le=200)):
    return {"items": store.focus_reviews(limit)}


@app.get("/api/media/time-segments")
async def media_time_segments(limit: int = Query(50, ge=1, le=200)):
    return {"items": store.time_segments(limit)}


@app.get("/api/media/change-gates")
async def media_change_gates(limit: int = Query(100, ge=1, le=300)):
    return {"items": store.change_gate_results(limit)}
