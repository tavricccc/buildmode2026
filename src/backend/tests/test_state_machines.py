"""Deterministic state machines (docs/01_PIPELINE.md §Event state machine)."""

import unittest

from ..domain.enums import EventStatus
from ..domain.policy import FallPolicy, HydrationPolicy
from ..state_machines import (
    FallContext,
    HydrationContext,
    fall_transition,
    hydration_transition,
)
from .helpers import observation

LYING = observation(fall={"posture": "lying", "near_floor": True,
                          "motionless": True, "confidence": 0.9})
LYING_LOW = observation(fall={"posture": "lying", "near_floor": True, "confidence": 0.2})
STANDING = observation()
DRINKING = observation(hydration={"container": "cup", "drinking_motion": True, "confidence": 0.9})


def run_fall(sequence, policy=None, now_ms=0):
    policy = policy or FallPolicy()
    status, history, trail = EventStatus.idle, [], []
    confirmed_at = None
    for index, obs in enumerate(sequence):
        history.append(obs)
        context = FallContext(
            subject_id="s", history=tuple(history), policy=policy,
            now_ms=now_ms or index * 1000, confirmed_at_ms=confirmed_at,
        )
        status, attrs = fall_transition(context, status)
        if status is EventStatus.confirmed and confirmed_at is None:
            confirmed_at = index * 1000
        if status is not EventStatus.confirmed:
            confirmed_at = None
        if status in {EventStatus.resolved, EventStatus.dismissed}:
            history.clear()
        trail.append((status, attrs))
    return trail


class TestFall(unittest.TestCase):
    def test_one_observation_suspects_but_does_not_confirm(self):
        trail = run_fall([STANDING, LYING])
        self.assertEqual(trail[-1][0], EventStatus.suspect)
        self.assertFalse(trail[-1][1]["alert_due"])

    def test_corroboration_confirms_and_raises_exactly_one_alert(self):
        trail = run_fall([STANDING, LYING, LYING, LYING])
        statuses = [s for s, _ in trail]
        self.assertEqual(statuses[1:], [EventStatus.suspect, EventStatus.confirmed,
                                        EventStatus.confirmed])
        self.assertEqual(sum(1 for _, a in trail if a["alert_due"]), 1)

    def test_a_motionless_person_keeps_corroborating(self):
        """The v4 bug this design exists to prevent.

        In v4 a motionless person produced no new observation, so a real
        fall was the one case that could never reach `confirmed`. Here the
        observations keep arriving because L1 is bypassed, and the count
        keeps rising.
        """
        trail = run_fall([LYING] * 6)
        self.assertEqual(trail[-1][0], EventStatus.confirmed)
        self.assertEqual(trail[-1][1]["corroborating_observations"], 6)

    def test_getting_up_before_corroboration_dismisses(self):
        trail = run_fall([LYING, STANDING])
        self.assertEqual(trail[-1][0], EventStatus.dismissed)

    def test_low_confidence_lying_is_not_a_fall(self):
        trail = run_fall([LYING_LOW, LYING_LOW, LYING_LOW])
        self.assertEqual(trail[-1][0], EventStatus.idle)

    def test_recovery_then_resolution(self):
        trail = run_fall([LYING, LYING, STANDING, STANDING])
        self.assertEqual([s for s, _ in trail][-2:], [EventStatus.recovering, EventStatus.resolved])

    def test_relapse_returns_to_confirmed(self):
        trail = run_fall([LYING, LYING, STANDING, LYING])
        self.assertEqual(trail[-1][0], EventStatus.confirmed)

    def test_no_recovery_alert_fires_once_after_the_window(self):
        policy = FallPolicy(no_recovery_alert_sec=60)
        context = FallContext(subject_id="s", history=(LYING, LYING), policy=policy,
                              now_ms=100_000, confirmed_at_ms=10_000, alert_sent=False)
        _, attrs = fall_transition(context, EventStatus.confirmed)
        self.assertTrue(attrs["alert_due"])
        self.assertEqual(attrs["alert_reason"], "no_recovery")

        already = FallContext(subject_id="s", history=(LYING, LYING), policy=policy,
                              now_ms=100_000, confirmed_at_ms=10_000, alert_sent=True)
        _, attrs = fall_transition(already, EventStatus.confirmed)
        self.assertFalse(attrs["alert_due"])

    def test_transitions_are_pure(self):
        history = (LYING, LYING)
        context = FallContext(subject_id="s", history=history, policy=FallPolicy(), now_ms=0)
        first = fall_transition(context, EventStatus.suspect)
        second = fall_transition(context, EventStatus.suspect)
        self.assertEqual(first, second)
        self.assertEqual(history, (LYING, LYING))


def run_hydration(sequence, policy=None, step_ms=1000, last_completed=None):
    policy = policy or HydrationPolicy()
    status, history, trail = EventStatus.idle, [], []
    started = None
    for index, obs in enumerate(sequence):
        history.append(obs)
        now = index * step_ms
        if status is EventStatus.idle:
            started = now
        context = HydrationContext(
            subject_id="s", history=tuple(history), policy=policy, now_ms=now,
            last_completed_at_ms=last_completed, started_at_ms=started,
        )
        status, attrs = hydration_transition(context, status)
        if attrs["counted"]:
            last_completed = now
            history.clear()
        trail.append((status, attrs))
    return trail


class TestHydration(unittest.TestCase):
    def test_a_full_session_counts_once(self):
        trail = run_hydration([DRINKING] * 4 + [STANDING])
        self.assertEqual(trail[-1][0], EventStatus.completed)
        self.assertEqual(sum(1 for _, a in trail if a["counted"]), 1)
        self.assertEqual(trail[-1][1]["estimated_ml"], HydrationPolicy().container_volume_ml)

    def test_a_single_frame_of_cup_near_face_is_not_a_drink(self):
        trail = run_hydration([DRINKING, STANDING])
        self.assertEqual(trail[-1][0], EventStatus.dismissed)

    def test_a_second_session_inside_the_cooldown_is_not_counted(self):
        """docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 11: replaying the same footage must not double-count."""
        policy = HydrationPolicy(session_cooldown_sec=45)
        trail = run_hydration([DRINKING] * 4 + [STANDING] + [DRINKING] * 4 + [STANDING],
                              policy=policy, step_ms=1000)
        self.assertEqual(sum(1 for _, a in trail if a["counted"]), 1)

    def test_a_session_after_the_cooldown_is_counted(self):
        policy = HydrationPolicy(session_cooldown_sec=2)
        trail = run_hydration([DRINKING] * 3 + [STANDING] + [DRINKING] * 3 + [STANDING],
                              policy=policy, step_ms=5000)
        self.assertEqual(sum(1 for _, a in trail if a["counted"]), 2)


if __name__ == "__main__":
    unittest.main()
