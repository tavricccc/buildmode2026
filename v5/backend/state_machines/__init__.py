"""Deterministic event state machines (v5 01 §Event state machine).

A model observation is evidence. Only these pure functions turn evidence
into a confirmed event, and they are pure on purpose: no clock reads, no
I/O, no model calls. Everything they need arrives in the context object,
which is what makes a replay reproducible and a disagreement about the
thresholds a code review rather than an argument about a log.
"""

from .fall import FallContext, fall_transition  # noqa: F401
from .hydration import HydrationContext, hydration_transition  # noqa: F401
