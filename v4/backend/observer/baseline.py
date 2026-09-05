"""Baseline comparison (v4 10).

The Observer compares the current short window against a 7/30-day
baseline. The comparison is pure-function so the scheduler can
re-run it without I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaselineComparison:
    short_window_days: int
    baseline_window_days: int
    deltas: dict[str, float]
    exceeds_threshold: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "short_window_days": self.short_window_days,
            "baseline_window_days": self.baseline_window_days,
            "deltas": dict(self.deltas),
            "exceeds_threshold": list(self.exceeds_threshold),
        }


def compare_to_baseline(
    short: dict[str, float],
    baseline: dict[str, float],
    *,
    short_window_days: int = 7,
    baseline_window_days: int = 30,
    change_threshold: float = 0.25,
) -> BaselineComparison:
    deltas: dict[str, float] = {}
    exceeds: list[str] = []
    keys = set(short) | set(baseline)
    for k in keys:
        b = baseline.get(k, 0.0)
        s = short.get(k, 0.0)
        if b == 0:
            deltas[k] = float("inf") if s else 0.0
            if s:
                exceeds.append(k)
            continue
        ratio = (s - b) / b
        deltas[k] = ratio
        if abs(ratio) >= change_threshold:
            exceeds.append(k)
    return BaselineComparison(
        short_window_days=short_window_days,
        baseline_window_days=baseline_window_days,
        deltas=deltas,
        exceeds_threshold=tuple(exceeds),
    )
