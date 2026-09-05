"""Long-term Observer (v4 10).

The Observer is a background service that runs the analysis model
slot against fixed-size daily summaries, not raw video. The full
implementation lands in a later commit; this round ships a typed
scaffold + unit-testable inputs.
"""

from .daily_summary import DailySummaryInput, build_daily_summary
from .baseline import BaselineComparison, compare_to_baseline
from .finding import ObserverFinding, build_finding
from .scheduler import ObserverScheduler, ObserverTrigger

__all__ = [
    "DailySummaryInput",
    "build_daily_summary",
    "BaselineComparison",
    "compare_to_baseline",
    "ObserverFinding",
    "build_finding",
    "ObserverScheduler",
    "ObserverTrigger",
]
