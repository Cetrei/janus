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


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)  # numerically stable softmax
    exp = np.exp(shifted)
    return exp / exp.sum()


class SFaceFaceVerifier(FaceVerifier):
    """Real local face verifier: SFace (128-dim embedding) + MiniFASNetV2/V1SE
    (liveness), per requisitos 6, 7, 8. Detection is either YuNet
    ("local:sface" or bare "local", the default) or SCRFD ("local:scrfd",
    opt-in) -- see the variant docs below.

    Multi-face frames are refused without comparison (INCONCLUSIVE,
    reason="multiple_faces") rather than picking one arbitrarily, since a
    silent pick would be a security-relevant decision made implicitly.

    Detection, quality-gating and embedding are shared with low_level.py
    (requisito 8bis) via _face_pipeline.py, so this class only adds what is
    specific to the 1:1 path: the multi-face refusal, liveness, and
    threshold-based decision.

    Variants (the part after the colon in a "local:<variant>" provider
    ref, resolved by ProviderRegistry per registry.py's ProviderRef):

    * "sface" (default, same as bare "local"): detection via YuNet
      (cv2.FaceDetectorYN). MIT-licensed weights, no license question.
      This is the only variant used before 2026-09-26 and remains the
      default so existing configuration and enrollments are unaffected.
    * "scrfd": detection via SCRFD (models.yaml's "scrfd" entry, manual
      onnxruntime plus anchor decoding via
      _face_pipeline.detect_faces_scrfd, since OpenCV has no built-in
      SCRFD wrapper). Added for better tolerance to head tilt/profile
      angles -- YuNet is trained mainly on frontal/near-frontal faces,
      while SCRFD scores meaningfully higher on WIDER FACE's Hard split
      (the profile/occlusion-heavy benchmark). LICENSE: SCRFD's weights
      carry InsightFace's own "non-commercial research purposes only"
      restriction, unlike YuNet/SFace/MiniFASNet. This variant is opt-in
      and only usable because the user explicitly accepted that license
      risk for this specific project (personal use, portfolio, not sold
      or distributed as a commercial product) -- see
      docs/specs/spec-18-biometrics.md's "Actualizacion 2026-09-26" note
      for the full reasoning and scope. Do not treat this as a general
      "InsightFace weights are fine" precedent for other projects.
      Enrollments are NOT interchangeable between "sface" and "scrfd"
      (different model_id, ModelMismatch forces re-enrollment on switch,
      requisito 18): crop framing/alignment for SFace's embedding depends
      on which detector's keypoints fed alignCrop, even though both
      variants use SFace for the embedding step itself.
    """

    id = _PROVIDER_ID

    # model_id per detector backend. "local:sface" (variant="sface", the
    # default when no variant is given) keeps the original model_id so
    # existing enrollments are unaffected. "local:scrfd" (variant="scrfd")
    # gets a distinct model_id: embeddings from different detector
    # backends are not comparable even though both use SFace for the
    # actual embedding, since crop framing/alignment depends on which
    # detector's keypoints fed alignCrop (requisito 18, ModelMismatch
    # forces re-enrollment on a backend switch, same as any model change).
    _MODEL_ID_BY_VARIANT = {
        "sface": _MODEL_ID,
        None: _MODEL_ID,  # "local" with no variant behaves like "local:sface"
        "scrfd": "scrfd-sface-minifasnet-v1",
    }

    def __init__(
        self,
        variant: str | None = None,
        model_cache: ModelCache | None = None,
        liveness_mode: str = "required",
    ) -> None:
        if variant not in self._MODEL_ID_BY_VARIANT:
            raise ValueError(
                f"Unknown local face variant '{variant}'; expected one of "
                f"{sorted(v for v in self._MODEL_ID_BY_VARIANT if v is not None)}"
            )
        # "scrfd" is opt-in and license-encumbered (InsightFace, see
        # providers/scrfd.py's module docstring and models.yaml's "scrfd"
        # entry) -- everything else about this class (liveness, embedding,
        # decision) is identical regardless of variant, only detection
        # differs, so the variant flag alone decides _detector_backend
        # rather than duplicating this whole class.
        self._detector_backend = "scrfd" if variant == "scrfd" else "yunet"
        self._model_id = self._MODEL_ID_BY_VARIANT[variant]
        if model_cache is None:
            raise ValueError("SFaceFaceVerifier requires a model_cache (see models.py)")
        self._cache = model_cache
        self._liveness_mode = liveness_mode
        self._detector: cv2.FaceDetectorYN | None = None
        self._scrfd_session = None  # only used when self._detector_backend == "scrfd"
        self._recognizer: cv2.FaceRecognizerSF | None = None
        # Liveness is an ensemble of two separate ONNX models (MiniFASNetV2 +
        # MiniFASNetV1SE); minivision-ai never published a single combined
        # file, so models.yaml has two entries and their softmax outputs are
        # averaged before argmax (see NOTICE / models.yaml comments).
        self._liveness_session_v2 = None  # onnxruntime.InferenceSession, loaded lazily
        self._liveness_session_v1se = None

    def _ensure_loaded(self, image_shape: tuple[int, int]) -> None:
        if self._detector_backend == "scrfd":
            if self._scrfd_session is None:
                scrfd_path = self._cache.resolve("scrfd")
                self._scrfd_session = pipeline.create_scrfd_session(str(scrfd_path))
        elif self._detector is None:
            yunet_path = self._cache.resolve("yunet")
            self._detector = pipeline.create_detector(str(yunet_path), image_shape)
        else:
            self._detector.setInputSize((image_shape[1], image_shape[0]))

        if self._recognizer is None:
            sface_path = self._cache.resolve("sface")
            self._recognizer = pipeline.create_recognizer(str(sface_path))

        if self._liveness_session_v2 is None or self._liveness_session_v1se is None:
            import onnxruntime  # local import: optional face extra

            v2_path = self._cache.resolve("minifasnet_v2")
            v1se_path = self._cache.resolve("minifasnet_v1se")
            self._liveness_session_v2 = onnxruntime.InferenceSession(str(v2_path))
            self._liveness_session_v1se = onnxruntime.InferenceSession(str(v1se_path))

    async def verify(self, image: bytes, enrollment: Enrollment) -> BiometricResult:
        if enrollment.model_id != self._model_id:
            raise ModelMismatch("face", enrollment.profile, self._model_id, enrollment.model_id)

        frame = pipeline.decode_image(image)
        self._ensure_loaded(frame.shape[:2])

        faces = (
            pipeline.detect_faces_scrfd(self._scrfd_session, frame)
            if self._detector_backend == "scrfd"
            else pipeline.detect_faces(self._detector, frame)
        )
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
        # Each MiniFASNet model gets its own expanded crop, scaled per its
        # own training convention (encoded in its weight filename, e.g.
        # 2.7_80x80_MiniFASNetV2.pth) rather than the tight YuNet bbox --
        # see _face_pipeline.crop_with_margin's docstring for why (the
        # model needs surrounding context, not just the face region, to
        # judge liveness) and its CAVEAT for what is/isn't confirmed about
        # the exact scale factors.
        crop_v2 = pipeline.crop_with_margin(frame, face, pipeline.MINIFASNET_SCALE_V2)
        crop_v1se = pipeline.crop_with_margin(frame, face, pipeline.MINIFASNET_SCALE_V1SE)

        live_score = self._ensemble_live_score(crop_v2, crop_v1se)
        return Liveness.PASS if live_score >= _LIVENESS_PASS_THRESHOLD else Liveness.FAIL

    def _ensemble_live_score(self, crop_v2: np.ndarray, crop_v1se: np.ndarray) -> float:
        """Averages the softmax outputs of both MiniFASNet models (V2 and
        V1SE) before taking the live-class probability, matching the
        upstream-recommended ensemble (see models.yaml comments / NOTICE).
        Each session outputs raw logits over 3 classes
        (live, print-attack, replay-attack); softmax is applied per-model
        before averaging, not after, since averaging raw logits is not
        equivalent to averaging probabilities. Each model gets its own
        crop (see _check_liveness) rather than a shared one, since their
        expected scale factors are tracked separately even though they
        currently share the same value.
        """
        probs = []
        for session, crop in (
            (self._liveness_session_v2, crop_v2),
            (self._liveness_session_v1se, crop_v1se),
        ):
            resized = cv2.resize(crop, (80, 80)).astype(np.float32) / 255.0
            input_tensor = np.transpose(resized, (2, 0, 1))[np.newaxis, ...]
            input_name = session.get_inputs()[0].name
            logits = session.run(None, {input_name: input_tensor})[0][0]
            probs.append(_softmax(logits))
        averaged = (probs[0] + probs[1]) / 2.0
        # Index 2 is the "live" class for this ONNX export, confirmed by two
        # separate manual verify runs against a real live face
        # ([0.029, 0.016, 0.956] and [0.030, 0.015, 0.955], both argmax=2).
        # This export's class order is NOT [fake, live, unused] as originally
        # assumed -- upstream's own test.py never hardcodes the index by
        # name, it only ever reaches it via argmax on its own weights, so
        # this was unverified for this third-party export until now. Which
        # of the remaining two indices (0, 1) maps to which spoof type is
        # still unconfirmed, but irrelevant for this binary live/not-live
        # read.
        return float(averaged[2]) if averaged.shape[-1] > 2 else float(averaged[0])

    def _result(
        self, decision: Decision, liveness: Liveness, quality_ok: bool, reason: str
    ) -> BiometricResult:
        return BiometricResult(
            decision=decision,
            liveness=liveness,
            quality_ok=quality_ok,
            reason=reason,
            provider_id=_PROVIDER_ID,
            model_id=self._model_id,
        )

    async def close(self) -> None:
        self._detector = None
        self._scrfd_session = None
        self._recognizer = None
        self._liveness_session_v2 = None
        self._liveness_session_v1se = None
