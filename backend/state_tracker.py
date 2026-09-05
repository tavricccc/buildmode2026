from __future__ import annotations

from typing import Any

from .schemas import VisionObservation


POSTURE_STATES = frozenset({"standing", "sitting", "lying"})
POSTURE_TRANSITIONS = {
    ("sitting", "standing"): "person_stood_up",
    ("standing", "sitting"): "person_sat_down",
    ("sitting", "lying"): "person_lay_down",
    ("standing", "lying"): "person_lay_down",
    ("lying", "standing"): "person_got_up",
    ("lying", "sitting"): "person_got_up",
}


def initial_state() -> dict[str, Any]:
    return {
        "stable_posture": "unknown",
        "stable_offset_ms": None,
        "candidate_posture": None,
        "candidate_count": 0,
        "candidate_first_offset_ms": None,
        "last_observed_offset_ms": None,
        "last_person_visible": None,
        "missing_count": 0,
        "last_transition": None,
        "schema_version": "posture-state.v1",
    }


def update_state(previous: dict[str, Any] | None, observation: VisionObservation,
                 window: dict[str, Any] | None = None, *, confirmations: int = 2) -> dict[str, Any]:
    """Turn noisy window-level posture observations into stable transitions.

    The returned ``transition`` is emitted only after the new posture appears in
    consecutive ordered observations. The event offset is estimated halfway
    between the last stable sample and the first sample of the new posture.
    """
    state = {**initial_state(), **(previous or {})}
    offset = int(observation.observed_at_offset_ms)
    result: dict[str, Any] = {"state": state, "transition": None, "ignored_out_of_order": False}

    # Parallel VLM calls may finish out of order. Never allow an older window
    # to roll the stable state backwards or create a duplicate transition.
    last_offset = state.get("last_observed_offset_ms")
    if last_offset is not None and offset <= int(last_offset):
        result["ignored_out_of_order"] = True
        return result

    # A missing/unknown observation is not evidence of a posture change. After
    # two consecutive misses we release the posture to unknown, avoiding stale
    # state being presented as the current location.
    if not observation.person_visible or observation.posture not in POSTURE_STATES:
        state["missing_count"] = int(state.get("missing_count") or 0) + 1
        state["candidate_posture"] = None
        state["candidate_count"] = 0
        state["candidate_first_offset_ms"] = None
        state["last_observed_offset_ms"] = offset
        state["last_person_visible"] = bool(observation.person_visible)
        if state["missing_count"] >= 2:
            state["stable_posture"] = "unknown"
            state["stable_offset_ms"] = offset
        return result

    state["missing_count"] = 0
    state["last_person_visible"] = True
    state["last_observed_offset_ms"] = offset
    posture = observation.posture
    stable = state.get("stable_posture", "unknown")

    # The first reliable posture establishes a baseline; it is not a false
    # "sat down" or "stood up" event.
    if stable not in POSTURE_STATES:
        state["stable_posture"] = posture
        state["stable_offset_ms"] = offset
        state["candidate_posture"] = None
        state["candidate_count"] = 0
        state["candidate_first_offset_ms"] = None
        return result

    if posture == stable:
        state["candidate_posture"] = None
        state["candidate_count"] = 0
        state["candidate_first_offset_ms"] = None
        return result

    if state.get("candidate_posture") != posture:
        state["candidate_posture"] = posture
        state["candidate_count"] = 1
        state["candidate_first_offset_ms"] = offset
        return result

    state["candidate_count"] = int(state.get("candidate_count") or 0) + 1
    if state["candidate_count"] < max(2, confirmations):
        return result

    event_type = POSTURE_TRANSITIONS.get((stable, posture))
    first_new_offset = int(state.get("candidate_first_offset_ms") or offset)
    previous_stable_offset = int(state.get("stable_offset_ms") or first_new_offset)
    occurred_offset = max(0, (previous_stable_offset + first_new_offset) // 2)
    transition = {
        "event_type": event_type,
        "domain": "person",
        "label": event_type.replace("_", " ") if event_type else f"person {stable} to {posture}",
        "from_state": stable,
        "to_state": posture,
        "occurred_offset_ms": occurred_offset,
        "first_observed_offset_ms": first_new_offset,
        "confirmed_offset_ms": offset,
        "confirmation_observations": state["candidate_count"],
        "source_window_start_ms": int((window or {}).get("start_offset_ms", offset)),
        "source_window_end_ms": int((window or {}).get("end_offset_ms", offset)),
        "evidence_frame_indexes": list(observation.supporting_frame_indexes),
        "confidence": round(min(0.99, max(0.0, observation.confidence) * min(1.0, state["candidate_count"] / max(2, confirmations))), 4),
        "detector": "temporal_posture_state_tracker",
        "schema_version": "posture-transition.v1",
    }
    if transition["event_type"]:
        result["transition"] = transition
        state["last_transition"] = transition

    state["stable_posture"] = posture
    state["stable_offset_ms"] = offset
    state["candidate_posture"] = None
    state["candidate_count"] = 0
    state["candidate_first_offset_ms"] = None
    return result
