"""Person detectors behind one narrow contract (docs/01_PIPELINE.md §L1).

Three implementations, all interchangeable:

``StubPersonDetector``   reads replay ground truth. Deterministic, zero
                         cost — the default before Setup downloads a model.
``MotionPersonDetector`` frame differencing via the FFmpeg we already
                         depend on. No extra install. Honest about its
                         weakness: a *motionless* person reads as absent,
                         which is precisely why the gate has a long exit
                         hysteresis, a heartbeat, and a high-risk bypass.
``OnnxPersonDetector``   YOLO11n person class through onnxruntime. The
                         real one. Imported lazily so that neither the
                         import nor the weights exist until the user picks
                         it in Setup (docs/04_SETUP_DEPLOY_VERIFY.md: no multi-GB download at start).
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from ..domain.enums import Health
from ..domain.l1_contract import PersonGateReading
from ..domain.timeutil import now_ms
from ..media import ffmpeg
from ..media.frames import FramePacket


class PersonDetector(Protocol):
    detector_id: str

    def detect(self, packet: FramePacket) -> PersonGateReading: ...

    def health(self) -> dict[str, Any]: ...


def _reading(
    detector_id: str,
    present: bool,
    confidence: float,
    started: float,
    health: Health = Health.ok,
) -> PersonGateReading:
    return PersonGateReading.parse(
        {
            "person_present": present,
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "observed_at_ms": now_ms(),
            "detector_id": detector_id,
            "inference_ms": int((time.perf_counter() - started) * 1000),
            "health": health.value,
        }
    )


class StubPersonDetector:
    """Ground-truth detector for replay fixtures and contract tests."""

    detector_id = "stub"

    def __init__(self, default_present: bool = False, confidence: float = 0.99) -> None:
        self.default_present = default_present
        self.confidence = confidence
        self._calls = 0

    def detect(self, packet: FramePacket) -> PersonGateReading:
        started = time.perf_counter()
        self._calls += 1
        annotation = packet.annotation or {}
        present = bool(annotation.get("person", self.default_present))
        # A fixture can force a detector fault to exercise the fail-open path.
        if annotation.get("detector_fault"):
            return _reading(self.detector_id, False, 0.0, started, Health.unavailable)
        confidence = float(annotation.get("person_confidence", self.confidence))
        return _reading(self.detector_id, present, confidence, started)

    def health(self) -> dict[str, Any]:
        return {"detector_id": self.detector_id, "status": Health.ok.value, "calls": self._calls}


class MotionPersonDetector:
    """Dependency-free presence proxy based on frame differencing.

    Decodes each sampled frame to a 32x24 grayscale thumbnail and compares
    it with the previous one. Above ``threshold`` mean absolute difference
    the scene is moving, which we report as presence.

    This is a *proxy*, not a person classifier, and it is documented as one
    in Setup: it cannot see a sleeping resident. The gate compensates
    structurally rather than by pretending otherwise — see ``gate.py``.
    """

    detector_id = "motion"

    def __init__(
        self,
        threshold: float = 3.0,
        thumb_width: int = 32,
        thumb_height: int = 24,
        saturation: float = 12.0,
    ) -> None:
        self.threshold = threshold
        self.thumb_width = thumb_width
        self.thumb_height = thumb_height
        #: difference at which confidence saturates to 1.0
        self.saturation = saturation
        self._previous: bytes | None = None
        self._calls = 0
        self._decode_failures = 0

    def detect(self, packet: FramePacket) -> PersonGateReading:
        started = time.perf_counter()
        self._calls += 1
        thumb = ffmpeg.decode_gray(packet.jpeg, self.thumb_width, self.thumb_height)
        if thumb is None:
            self._decode_failures += 1
            # Decode failure is a detector fault, never "no person".
            return _reading(self.detector_id, False, 0.0, started, Health.unavailable)

        previous, self._previous = self._previous, thumb
        if previous is None:
            # No baseline yet: report unknown-as-fault so the gate fails open
            # instead of reading the first frame of a session as an empty room.
            return _reading(self.detector_id, False, 0.0, started, Health.degraded)

        total = sum(abs(a - b) for a, b in zip(thumb, previous))
        mean_diff = total / float(len(thumb))
        present = mean_diff >= self.threshold
        confidence = min(1.0, mean_diff / self.saturation) if present else 1.0 - min(
            1.0, mean_diff / self.threshold
        )
        return _reading(self.detector_id, present, confidence, started)

    def health(self) -> dict[str, Any]:
        status = Health.ok if self._decode_failures == 0 else Health.degraded
        return {
            "detector_id": self.detector_id,
            "status": status.value,
            "calls": self._calls,
            "decode_failures": self._decode_failures,
            "note": "motion proxy — cannot see a motionless person",
        }


class OnnxPersonDetector:
    """YOLO11n (person class only) via onnxruntime.

    Nothing about onnxruntime is imported at module import time, and the
    weights are not touched until :meth:`load` is called from Setup. A
    missing model or a missing runtime degrades to ``Health.unavailable``,
    which the gate treats as fail-open rather than as an empty room.
    """

    detector_id = "yolo11n"
    #: COCO class index for "person"
    PERSON_CLASS = 0

    def __init__(
        self,
        model_path: str,
        input_size: int = 640,
        confidence_threshold: float = 0.45,
        providers: list[str] | None = None,
    ) -> None:
        self.model_path = model_path
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.providers = providers
        self._session: Any = None
        self._np: Any = None
        self._load_error: str | None = None
        self._calls = 0

    def load(self) -> bool:
        """Import the runtime and open the model. Safe to call repeatedly."""
        if self._session is not None:
            return True
        try:
            import numpy  # noqa: PLC0415
            import onnxruntime  # noqa: PLC0415
        except ImportError as exc:
            self._load_error = f"runtime_missing: {exc}"
            return False
        try:
            providers = self.providers or onnxruntime.get_available_providers()
            self._session = onnxruntime.InferenceSession(self.model_path, providers=providers)
            self._np = numpy
            self._load_error = None
            return True
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"load_failed: {exc}"
            return False

    def detect(self, packet: FramePacket) -> PersonGateReading:
        started = time.perf_counter()
        self._calls += 1
        if not self.load():
            return _reading(self.detector_id, False, 0.0, started, Health.unavailable)

        raw = ffmpeg.decode_rgb(packet.jpeg, self.input_size, self.input_size)
        if raw is None:
            return _reading(self.detector_id, False, 0.0, started, Health.unavailable)

        np = self._np
        tensor = (
            np.frombuffer(raw, dtype=np.uint8)
            .reshape(self.input_size, self.input_size, 3)
            .astype(np.float32)
            / 255.0
        )
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]

        try:
            name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {name: tensor})
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"inference_failed: {exc}"
            return _reading(self.detector_id, False, 0.0, started, Health.unavailable)

        score = self._best_person_score(outputs[0])
        present = score >= self.confidence_threshold
        return _reading(self.detector_id, present, score if present else 1.0 - score, started)

    def _best_person_score(self, output: Any) -> float:
        """Peak person-class score from a YOLO ``(1, 4+nc, n)`` head.

        We only need the maximum, never the boxes — the contract forbids
        this layer from reporting *where* anyone is, so NMS would be
        wasted work and a temptation to leak location downstream.
        """
        np = self._np
        arr = np.squeeze(output)
        if arr.ndim != 2:
            return 0.0
        # Normalise to (channels, anchors); ultralytics exports (4+nc, n).
        if arr.shape[0] < arr.shape[1]:
            channels = arr
        else:
            channels = arr.T
        if channels.shape[0] < 5:
            return 0.0
        row = channels[4 + self.PERSON_CLASS]
        return float(np.max(row))

    def health(self) -> dict[str, Any]:
        if self._load_error is not None:
            status = Health.unavailable
        elif self._session is None:
            status = Health.unknown
        else:
            status = Health.ok
        return {
            "detector_id": self.detector_id,
            "status": status.value,
            "calls": self._calls,
            "model_path": self.model_path,
            "error": self._load_error,
        }


DETECTOR_REGISTRY: dict[str, str] = {
    "stub": "Replay ground truth — deterministic, no install, fixtures only",
    "motion": "FFmpeg frame differencing — no extra install, motion proxy",
    "yolo11n": "YOLO11n person class via onnxruntime — needs model download",
}


def build_detector(detector_id: str, **kwargs: Any) -> PersonDetector:
    if detector_id == "stub":
        return StubPersonDetector(**kwargs)
    if detector_id == "motion":
        return MotionPersonDetector(**kwargs)
    if detector_id == "yolo11n":
        return OnnxPersonDetector(**kwargs)
    raise ValueError(f"unknown detector_id: {detector_id!r}")
