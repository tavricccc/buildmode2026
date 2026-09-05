"""The debounced person gate (v5 01 §L1, v5 00 items 3–5).

The gate turns a stream of noisy detector readings into the single
four-valued decision the scheduler acts on. Three properties are
load-bearing and each one is here rather than in the caller:

*Hysteresis.*  Entering "person present" is deliberately cheap
(``frames_to_enter``, default 2) and leaving it is deliberately expensive
(``frames_to_exit``, default 4). The asymmetry is the safety margin: the
cost of a false *present* is one extra Gemini call, the cost of a false
*absent* is a missed fall. For the same reason the gate starts in the
present state, so a cold start cannot skip a window on its first reading.

*Staleness.*  A reading older than ``stale_after_ms`` stops being an
answer. It becomes ``stale``, which does not permit a skip.

*Fail-open.*  A detector that is unavailable, degraded, or has never
answered yields ``unavailable``, which also does not permit a skip. v5 00
item 5: a broken detector must never be read as an empty room.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import Health, L1Decision
from ..domain.l1_contract import PersonGateDecision, PersonGateReading
from ..domain.policy import L1Policy
from ..domain.timeutil import now_ms


class PersonGate:
    def __init__(self, policy: L1Policy) -> None:
        self.policy = policy
        self._last: PersonGateReading | None = None
        # Cold start assumes someone *is* present. With no evidence either
        # way, "absent" is the unsafe default: it would let the very first
        # healthy reading authorise a skip and bypass the exit hysteresis
        # entirely. Starting present means the room has to be shown empty
        # frames_to_exit times before any window is skipped.
        self._state: bool = True
        self._streak_present = 0
        self._streak_absent = 0
        self._flips = 0
        self._skips_permitted = 0
        self._fail_opens = 0

    # -- ingest ----------------------------------------------------------

    def observe(self, reading: PersonGateReading) -> None:
        """Fold one detector reading into the debounced state."""
        self._last = reading

        if Health(reading.health) is not Health.ok:
            # A fault contributes to neither streak: an unhealthy detector
            # must not be able to argue the room into "empty".
            self._streak_present = 0
            self._streak_absent = 0
            return

        confident = reading.confidence >= self.policy.confidence_threshold
        if reading.person_present and confident:
            self._streak_present += 1
            self._streak_absent = 0
        else:
            self._streak_absent += 1
            self._streak_present = 0

        if not self._state and self._streak_present >= self.policy.frames_to_enter:
            self._state = True
            self._flips += 1
        elif self._state and self._streak_absent >= self.policy.frames_to_exit:
            self._state = False
            self._flips += 1

    # -- decide ----------------------------------------------------------

    def decide(self, at_ms: int | None = None) -> PersonGateDecision:
        at = now_ms() if at_ms is None else at_ms

        if not self.policy.enabled:
            # The gate being switched off means "always let L2 decide",
            # never "assume nobody is home".
            self._fail_opens += 1
            return self._decision(
                L1Decision.unavailable, 0.0, at, 0, Health.unknown, "l1_disabled"
            )

        if self._last is None:
            self._fail_opens += 1
            return self._decision(
                L1Decision.unavailable, 0.0, at, 0, Health.unknown, "no_reading_yet"
            )

        age = max(0, at - self._last.observed_at_ms)
        health = Health(self._last.health)

        if health in {Health.unavailable, Health.unknown}:
            self._fail_opens += 1
            return self._decision(
                L1Decision.unavailable, 0.0, at, age, health, f"detector_{health.value}"
            )

        if age > self.policy.stale_after_ms:
            self._fail_opens += 1
            return self._decision(
                L1Decision.stale,
                self._last.confidence,
                at,
                age,
                health,
                f"reading_age_{age}ms_over_{self.policy.stale_after_ms}ms",
            )

        if self._state:
            return self._decision(
                L1Decision.person_present, self._last.confidence, at, age, health, "debounced_present"
            )

        # A degraded-but-fresh detector may say "present" but may not be
        # trusted to say "absent".
        if health is Health.degraded:
            self._fail_opens += 1
            return self._decision(
                L1Decision.unavailable, self._last.confidence, at, age, health, "detector_degraded"
            )

        self._skips_permitted += 1
        return self._decision(
            L1Decision.no_person, self._last.confidence, at, age, health, "debounced_absent"
        )

    def _decision(
        self,
        kind: L1Decision,
        confidence: float,
        at: int,
        age: int,
        health: Health,
        reason: str,
    ) -> PersonGateDecision:
        streak = self._streak_present if kind is L1Decision.person_present else self._streak_absent
        return PersonGateDecision.parse(
            {
                "decision": kind.value,
                "confidence": round(confidence, 4),
                "decided_at_ms": at,
                "detector_id": self._last.detector_id if self._last else self.policy.detector_id,
                "health": health.value,
                "consecutive_frames": streak,
                "age_ms": age,
                "reason": reason,
            }
        )

    # -- introspection ---------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        return {
            "state": "present" if self._state else "absent",
            "streak_present": self._streak_present,
            "streak_absent": self._streak_absent,
            "flips": self._flips,
            "skips_permitted": self._skips_permitted,
            "fail_opens": self._fail_opens,
            "last_reading_at_ms": self._last.observed_at_ms if self._last else None,
        }

    def reset(self) -> None:
        self._last = None
        self._state = True
        self._streak_present = 0
        self._streak_absent = 0
