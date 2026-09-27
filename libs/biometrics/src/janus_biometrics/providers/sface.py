from __future__ import annotations

import logging

import cv2
import numpy as np

from janus_biometrics import _face_pipeline as pipeline
from janus_biometrics.base import (
    BiometricResult,
    Decision,
    Enrollment,
    FaceVerifier,
    Liveness,
)
from janus_biometrics.errors import ModelMismatch
from janus_biometrics.models import ModelCache

logger = logging.getLogger(__name__)

_PROVIDER_ID = "local"
_MODEL_ID = "sface-yunet-minifasnet-v1"

_LIVENESS_PASS_THRESHOLD = 0.5


class SFaceFaceVerifier(FaceVerifier):
    """Real local face verifier: YuNet (detection) + MiniFASNetV2/V1SE
    (liveness) + SFace (128-dim embedding), per requisitos 6, 7, 8.

    Multi-face frames are refused without comparison (INCONCLUSIVE,
    reason="multiple_faces") rather than picking one arbitrarily, since a
    silent pick would be a security-relevant decision made implicitly.

    Detection, quality-gating and embedding are shared with low_level.py
    (requisito 8bis) via _face_pipeline.py, so this class only adds what is
    specific to the 1:1 path: the multi-face refusal, liveness, and
    threshold-based decision.
    """

    id = _PROVIDER_ID

    def __init__(
        self,
        variant: str | None = None,
        model_cache: ModelCache | None = None,
        liveness_mode: str = "required",
    ) -> None:
        del variant  # single variant for now; kept for registry symmetry
        if model_cache is None:
            raise ValueError("SFaceFaceVerifier requires a model_cache (see models.py)")
        self._cache = model_cache
        self._liveness_mode = liveness_mode
        self._detector: cv2.FaceDetectorYN | None = None
        self._recognizer: cv2.FaceRecognizerSF | None = None
        self._liveness_session = None  # onnxruntime.InferenceSession, loaded lazily

    def _ensure_loaded(self, image_shape: tuple[int, int]) -> None:
        if self._detector is None:
            yunet_path = self._cache.resolve("yunet")
            self._detector = pipeline.create_detector(str(yunet_path), image_shape)
        else:
            self._detector.setInputSize((image_shape[1], image_shape[0]))

        if self._recognizer is None:
            sface_path = self._cache.resolve("sface")
            self._recognizer = pipeline.create_recognizer(str(sface_path))

        if self._liveness_session is None:
            import onnxruntime  # local import: optional face extra

            minifasnet_path = self._cache.resolve("minifasnet")
            self._liveness_session = onnxruntime.InferenceSession(str(minifasnet_path))

    async def verify(self, image: bytes, enrollment: Enrollment) -> BiometricResult:
        if enrollment.model_id != _MODEL_ID:
            raise ModelMismatch("face", enrollment.profile, _MODEL_ID, enrollment.model_id)

        frame = pipeline.decode_image(image)
        self._ensure_loaded(frame.shape[:2])

        faces = pipeline.detect_faces(self._detector, frame)
        if len(faces) == 0:
            return self._result(
                Decision.INCONCLUSIVE, Liveness.NOT_CHECKED, False, "no_face_detected"
            )
        if len(faces) > 1:
            return self._result(
                Decision.INCONCLUSIVE, Liveness.NOT_CHECKED, False, "multiple_faces"
            )

        face = faces[0]
        quality_ok, quality_reason = pipeline.check_quality(frame, face)
        if not quality_ok:
            return self._result(Decision.INCONCLUSIVE, Liveness.NOT_CHECKED, False, quality_reason)

        liveness = self._check_liveness(frame, face)
        embedding = pipeline.embed_face(self._recognizer, frame, face)
        score = pipeline.cosine_similarity(embedding, enrollment.centroid)

        decision = Decision.HIGH if score >= 0.363 else Decision.LOW
        # 0.363 is SFace's own published reference cosine threshold, used
        # here only as a conservative baseline; policy.decide() in the
        # caller (BiometricService) is what actually applies the
        # configured/calibrated Thresholds. This provider reports a
        # provisional decision so callers that bypass the service still
        # get a sane default, with calibration_recommended left to policy.
        return self._result(decision, liveness, True, "ok")

    def _check_liveness(self, frame: np.ndarray, face: np.ndarray) -> Liveness:
        x, y, w, h = face[:4].astype(int)
        x, y = max(x, 0), max(y, 0)
        crop = frame[y : y + h, x : x + w]
        resized = cv2.resize(crop, (80, 80)).astype(np.float32) / 255.0
        input_tensor = np.transpose(resized, (2, 0, 1))[np.newaxis, ...]

        input_name = self._liveness_session.get_inputs()[0].name
        outputs = self._liveness_session.run(None, {input_name: input_tensor})
        if outputs[0].shape[-1] > 1:
            live_score = float(outputs[0][0][1])
        else:
            live_score = float(outputs[0][0][0])

        return Liveness.PASS if live_score >= _LIVENESS_PASS_THRESHOLD else Liveness.FAIL

    def _result(
        self, decision: Decision, liveness: Liveness, quality_ok: bool, reason: str
    ) -> BiometricResult:
        return BiometricResult(
            decision=decision,
            liveness=liveness,
            quality_ok=quality_ok,
            reason=reason,
            provider_id=_PROVIDER_ID,
            model_id=_MODEL_ID,
        )

    async def close(self) -> None:
        self._detector = None
        self._recognizer = None
        self._liveness_session = None
