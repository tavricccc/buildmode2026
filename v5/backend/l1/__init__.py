"""L1: local person gate (v5 01 §L1).

This layer answers one question — *is a person in frame?* — and nothing
else. No posture, no identity, no fall, no hydration, no emotion. That
restraint is the whole point: it is what makes the layer cheap enough to
run continuously, and what keeps every semantic judgement in L2 where it
can be audited against a schema.
"""

from .detector import (  # noqa: F401
    DETECTOR_REGISTRY,
    MotionPersonDetector,
    PersonDetector,
    StubPersonDetector,
    build_detector,
)
from .gate import PersonGate  # noqa: F401
