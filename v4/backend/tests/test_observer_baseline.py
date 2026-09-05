"""Observer baseline comparison tests."""

from __future__ import annotations

from v4.backend.observer.baseline import compare_to_baseline


def test_no_change_when_within_threshold() -> None:
    cmp = compare_to_baseline({"fall": 1.0}, {"fall": 1.05}, change_threshold=0.25)
    assert "fall" not in cmp.exceeds_threshold


def test_change_above_threshold() -> None:
    cmp = compare_to_baseline({"fall": 2.0}, {"fall": 1.0}, change_threshold=0.25)
    assert "fall" in cmp.exceeds_threshold
    assert cmp.deltas["fall"] == 1.0


def test_zero_baseline_with_nonzero_short() -> None:
    cmp = compare_to_baseline({"fall": 1.0}, {"fall": 0.0}, change_threshold=0.25)
    assert "fall" in cmp.exceeds_threshold
