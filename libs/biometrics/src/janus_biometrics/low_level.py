from __future__ import annotations

from janus_biometrics import _face_pipeline as pipeline
from janus_biometrics.base import FaceEmbedding
from janus_biometrics.models import ModelCache

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

__all__ = ["detect_and_embed_faces"]


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
    frame = pipeline.decode_image(image)
    detector = pipeline.create_detector(str(model_cache.resolve("yunet")), frame.shape[:2])
    recognizer = pipeline.create_recognizer(str(model_cache.resolve("sface")))

    results: list[FaceEmbedding] = []
    for face in pipeline.detect_faces(detector, frame):
        quality_ok, _reason = pipeline.check_quality(frame, face)
        embedding = pipeline.embed_face(recognizer, frame, face)
        results.append(FaceEmbedding(embedding=embedding, quality_ok=quality_ok))

    return results
