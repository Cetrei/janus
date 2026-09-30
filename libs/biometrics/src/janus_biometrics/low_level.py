from __future__ import annotations

from janus_biometrics import _face_pipeline as pipeline
from janus_biometrics.base import FaceEmbedding, PcmAudio, VoiceEmbedding
from janus_biometrics.models import ModelCache
from janus_biometrics.providers.speaker_wespeaker import (
    _MIN_SPEECH_S_DEFAULT,
    SherpaWeSpeakerExtractor,
    _trim_silence,
)

# Bounded exception (spec-18, requisito 8bis): raw multi-face detection +
# embedding for libs/presence's 1:N identification, which cannot reuse
# BiometricService/verify_face without breaking its 1:1 guarantee (rejects
# multi-face, never exposes the raw vector, requisito 16).
#
# detect_and_embed_faces is deliberately NOT part of BiometricService, does
# not go through ProviderRegistry, applies no liveness, no threshold, no
# comparison against any enrolled template, and is not subject to the
# attempt-limiting/lockout policy (requisito 13). It reuses YuNet
# (detection) and SFace (embedding) from the same local:sface chain via
# _face_pipeline.py, so this module adds no new model code of its own.
#
# Any caller of this function receives raw biometric data (embeddings for
# every face found in the image, unfiltered by multi-face or quality
# rejection beyond the per-face quality_ok flag) and is responsible for its
# own safe handling of that data. This is a deliberate exception to the
# rest of this library's 1:1, no-raw-biometrics-out guarantee; its use is
# scoped to libs/presence.

__all__ = ["FaceEmbedder", "VoiceEmbedder", "detect_and_embed_faces", "extract_voice_embedding"]

_NOMINAL_INPUT_SHAPE = (240, 320)


def _unit_length(embedding: list[float]) -> list[float]:
    length = sum(value * value for value in embedding) ** 0.5
    if length == 0.0:
        return list(embedding)
    return [value / length for value in embedding]


class FaceEmbedder:
    def __init__(self, model_cache: ModelCache, normalized: bool = False) -> None:
        self._detector = pipeline.create_detector(
            str(model_cache.resolve("yunet")), _NOMINAL_INPUT_SHAPE
        )
        self._recognizer = pipeline.create_recognizer(str(model_cache.resolve("sface")))
        self._input_shape = _NOMINAL_INPUT_SHAPE
        self._normalized = normalized

    def embed(self, image: bytes) -> list[FaceEmbedding]:
        if self._detector is None or self._recognizer is None:
            raise RuntimeError("FaceEmbedder is closed")
        frame = pipeline.decode_image(image)
        self._fit_detector(frame.shape[:2])
        results: list[FaceEmbedding] = []
        for face in pipeline.detect_faces(self._detector, frame):
            quality_ok, _reason = pipeline.check_quality(frame, face)
            embedding = pipeline.embed_face(self._recognizer, frame, face)
            if self._normalized:
                embedding = _unit_length(embedding)
            bbox = pipeline.face_bbox(frame, face)
            results.append(FaceEmbedding(embedding=embedding, quality_ok=quality_ok, bbox=bbox))
        return results

    def close(self) -> None:
        self._detector = None
        self._recognizer = None

    def _fit_detector(self, shape: tuple[int, int]) -> None:
        if shape == self._input_shape:
            return
        pipeline.fit_detector_input(self._detector, shape)
        self._input_shape = shape


def detect_and_embed_faces(image: bytes, model_cache: ModelCache) -> list[FaceEmbedding]:
    """Detects every face in `image` and returns its raw SFace embedding.

    Unlike the 1:1 `local:sface` provider, this does not reject frames with
    more than one face: each detected face is processed independently,
    since for 1:N identification every face is a potentially distinct
    person and all of them matter (requisito 8bis). No liveness check, no
    threshold, no comparison against any enrolled template: this is only
    the detection + embedding step, reused as-is to avoid duplicating that
    code (spec-18 handoff note).

    A face that fails the same quality gate used by the 1:1 chain (too
    small, too blurry, or badly lit) is still embedded and returned, but
    flagged `quality_ok=False`: this function makes no rejection decisions
    of its own, so the caller (libs/presence) decides whether a low-quality
    embedding is still useful for its own matching threshold, rather than
    having a fabricated placeholder vector silently stand in for a real
    one.
    """
    embedder = FaceEmbedder(model_cache)
    try:
        return embedder.embed(image)
    finally:
        embedder.close()


class VoiceEmbedder:
    """Reusable WeSpeaker embedding extractor (requisito 8ter b): resolves the
    model and builds the ONNX session once, so a caller that embeds many
    utterances does not re-hash and reload the model each time. Like
    FaceEmbedder it is not thread safe: use one per thread. Needs the `voice`
    extra (sherpa-onnx).

    Same bounded exception as detect_and_embed_faces: no threshold, no
    comparison against any enrolled template, no liveness, outside
    BiometricService and its attempt policy. The caller receives raw
    biometric data and owns its safe handling.
    """

    def __init__(
        self, model_cache: ModelCache, min_speech_s: float = _MIN_SPEECH_S_DEFAULT
    ) -> None:
        self._extractor: SherpaWeSpeakerExtractor | None = SherpaWeSpeakerExtractor(
            model_cache.resolve("wespeaker")
        )
        self._min_speech_s = min_speech_s

    def embed(self, audio: PcmAudio) -> VoiceEmbedding:
        """Embeds `audio` after trimming silence. Audio too short to embed at
        all makes the extractor raise BiometricsError; audio that embeds but
        is under `min_speech_s` comes back flagged `quality_ok=False`, so the
        caller decides, instead of a placeholder vector standing in."""
        if self._extractor is None:
            raise RuntimeError("VoiceEmbedder is closed")
        trimmed = _trim_silence(audio)
        speech_s = len(trimmed.samples) / 2 / trimmed.sample_rate  # 16-bit mono PCM
        embedding = self._extractor.embed(trimmed)
        return VoiceEmbedding(
            embedding=embedding,
            speech_s=speech_s,
            quality_ok=speech_s >= self._min_speech_s,
        )

    def close(self) -> None:
        self._extractor = None


def extract_voice_embedding(audio: PcmAudio, model_cache: ModelCache) -> VoiceEmbedding:
    """One shot voice counterpart of `detect_and_embed_faces` (requisito 8ter b).
    Takes the model cache explicitly, like the face function, since the
    library has no global one."""
    embedder = VoiceEmbedder(model_cache)
    try:
        return embedder.embed(audio)
    finally:
        embedder.close()
