from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from janus_biometrics import _face_pipeline as pipeline
from janus_biometrics.base import Enrollment, PcmAudio
from janus_biometrics.errors import EnrollmentError
from janus_biometrics.models import ModelCache

# Requisito 15: minimum sample counts before an Enrollment can be built.
# Face: 5 images with angle/lighting variation. Voice: 5 utterances of at
# least 3s each, ideally from separate sessions -- MIN_VOICE_UTTERANCE_S is
# enforced here (enrollment-time quality gate); the *verification*-time
# minimum speech duration (requisito 9, default 2.5s, "too_short") is a
# separate, lower bar checked by the voice provider itself, not here.
MIN_FACE_SAMPLES = 5
MIN_VOICE_SAMPLES = 5
MIN_VOICE_UTTERANCE_S = 3.0


def enroll_face(images: list[bytes], model_cache: ModelCache) -> Enrollment:
    """Builds a face Enrollment from raw sample images (requisito 15).

    Reuses the exact same detector/embedder as the `local:sface` chain
    (_face_pipeline.py) so an embedding produced here is directly
    comparable to what SFaceFaceVerifier.verify() computes at
    verification time -- a separate embedding path would risk a subtle
    mismatch (different alignment, different detector version) that only
    surfaces as unexplained low scores later.

    Each image must contain exactly one face: zero faces or more than one
    is an EnrollmentError (requisito 8's `multiple_faces` handling is a
    *verification*-time INCONCLUSIVE, not an error, because a live capture
    can retry; enrollment fails hard instead so a bad sample set is never
    silently used to build a template, since the caller controls sample
    selection and can just supply a better image). Quality gating
    (requisito 8's sharpness/luminance/size checks) applies here too, for
    the same reason: a blurry or badly-lit enrollment sample degrades the
    template for every future verification against it, unlike a single
    bad verification attempt which just fails that one attempt.
    """
    if len(images) < MIN_FACE_SAMPLES:
        raise EnrollmentError(
            f"Face enrollment requires at least {MIN_FACE_SAMPLES} samples, got {len(images)}"
        )

    detector = None
    recognizer = pipeline.create_recognizer(str(model_cache.resolve("sface")))
    embeddings: list[list[float]] = []

    for index, image in enumerate(images):
        frame = pipeline.decode_image(image)
        if detector is None:
            yunet_path = str(model_cache.resolve("yunet"))
            detector = pipeline.create_detector(yunet_path, frame.shape[:2])
        else:
            detector.setInputSize((frame.shape[1], frame.shape[0]))

        faces = pipeline.detect_faces(detector, frame)
        if len(faces) == 0:
            raise EnrollmentError(f"Sample {index}: no face detected")
        if len(faces) > 1:
            raise EnrollmentError(f"Sample {index}: more than one face detected")

        face = faces[0]
        quality_ok, reason = pipeline.check_quality(frame, face)
        if not quality_ok:
            raise EnrollmentError(f"Sample {index}: failed quality gate ({reason})")

        embeddings.append(pipeline.embed_face(recognizer, frame, face))

    return Enrollment(
        kind="face",
        profile="owner",
        model_id="sface-yunet-minifasnet-v1",
        dim=pipeline.EMBEDDING_DIM,
        embeddings=embeddings,
        centroid=_centroid(embeddings),
        samples=len(embeddings),
        created_at=datetime.now(UTC),
    )


class VoiceFeatureExtractor(Protocol):
    """Turns normalized PcmAudio into a fixed-size speaker embedding.

    Deliberately a Protocol, not a concrete import of any specific
    fbank/embedding library: spec-18's own Open Questions list the
    frontend choice ("evaluar speakeronnx ... o kaldi-native-fbank, y
    confirmar wheels de aarch64 y de Windows") as unresolved, and neither
    package is installed in this environment. Picking one here would be
    an Architect-level dependency decision made unilaterally mid-task,
    not an Implementer one -- so enroll_voice takes this as an injected
    collaborator instead of importing a concrete library, exactly the
    same shape providers/speaker_wespeaker.py needs once that question is
    resolved (see that module's own docstring for the full status)."""

    def embed(self, audio: PcmAudio) -> list[float]: ...


def enroll_voice(
    recordings: list[PcmAudio], extractor: VoiceFeatureExtractor, model_id: str
) -> Enrollment:
    """Builds a voice Enrollment from raw utterances (requisito 15).

    `extractor` performs the fbank-extraction + embedding step (see
    VoiceFeatureExtractor's docstring for why this is injected rather
    than hardcoded); `model_id` is passed in rather than hardcoded here
    for the same reason -- this module has no opinion on which speaker
    model produced the embedding, only on the enrollment bookkeeping
    (sample count, centroid, timestamp) around it.
    """
    if len(recordings) < MIN_VOICE_SAMPLES:
        raise EnrollmentError(
            f"Voice enrollment requires at least {MIN_VOICE_SAMPLES} samples, "
            f"got {len(recordings)}"
        )

    embeddings: list[list[float]] = []
    for index, audio in enumerate(recordings):
        duration_s = len(audio.samples) / 2 / audio.sample_rate  # 16-bit mono PCM
        if duration_s < MIN_VOICE_UTTERANCE_S:
            raise EnrollmentError(
                f"Sample {index}: utterance is {duration_s:.1f}s, "
                f"below the {MIN_VOICE_UTTERANCE_S}s enrollment minimum"
            )
        embeddings.append(extractor.embed(audio))

    dim = len(embeddings[0])
    return Enrollment(
        kind="voice",
        profile="owner",
        model_id=model_id,
        dim=dim,
        embeddings=embeddings,
        centroid=_centroid(embeddings),
        samples=len(embeddings),
        created_at=datetime.now(UTC),
    )


def _centroid(embeddings: list[list[float]]) -> list[float]:
    dim = len(embeddings[0])
    return [statistics.fmean(vec[i] for vec in embeddings) for i in range(dim)]


@dataclass(frozen=True)
class CalibrationResult:
    """Output of calibrate() (requisito 19). `calibration_recommended` is
    always False here: this IS the calibration, unlike policy.Thresholds's
    own default which warns until a CalibrationResult like this one has
    actually been produced and applied."""

    t_high: float
    t_low: float
    genuine_scores: list[float]
    impostor_scores: list[float] | None
    target_far: float
    target_frr: float


def calibrate(
    genuine_embeddings: list[list[float]],
    target_frr: float = 0.05,
    impostor_embeddings: list[list[float]] | None = None,
    target_far: float = 0.01,
) -> CalibrationResult:
    """Leave-one-out cross-validation over the owner's own enrollment
    samples (requisito 19). For each embedding, scores it against the
    centroid of every *other* embedding (never against itself, which
    would trivially score 1.0 and bias the distribution upward) to get a
    realistic distribution of genuine scores.

    Without impostor samples: t_low is set to the target_frr-th percentile
    of the genuine distribution (so at most target_frr of genuine
    attempts would fall below it) and t_high defaults to the midpoint
    between that and 1.0 -- conservative, and the caller is expected to
    still show a calibration warning (this function does not know about
    Thresholds.calibration_recommended, that flag belongs to whoever
    constructs the Thresholds from this result).

    With impostor samples (embeddings of other people, requisito 19's
    `--impostors DIR`): t_high is the lowest threshold that keeps the
    fraction of impostor scores at or above it under target_far, and
    t_low is still the genuine-distribution floor from above -- so a
    calibrated MEDIUM band is never wider than what the impostor data
    actually supports.
    """
    if len(genuine_embeddings) < 2:
        raise EnrollmentError("calibrate() needs at least 2 genuine samples for leave-one-out")

    genuine_scores = _leave_one_out_scores(genuine_embeddings)
    t_low = _percentile(genuine_scores, target_frr)

    if impostor_embeddings:
        centroid = _centroid(genuine_embeddings)
        impostor_scores = [
            pipeline.cosine_similarity(vec, centroid) for vec in impostor_embeddings
        ]
        t_high = _far_threshold(impostor_scores, target_far)
        t_high = max(t_high, t_low)  # never let t_high < t_low from a tiny impostor sample
    else:
        impostor_scores = None
        t_high = t_low + (1.0 - t_low) / 2.0

    return CalibrationResult(
        t_high=t_high,
        t_low=t_low,
        genuine_scores=genuine_scores,
        impostor_scores=impostor_scores,
        target_far=target_far,
        target_frr=target_frr,
    )


def _leave_one_out_scores(embeddings: list[list[float]]) -> list[float]:
    scores = []
    for i, held_out in enumerate(embeddings):
        others = embeddings[:i] + embeddings[i + 1 :]
        centroid = _centroid(others)
        scores.append(pipeline.cosine_similarity(held_out, centroid))
    return scores


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = round(fraction * (len(ordered) - 1))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _far_threshold(impostor_scores: list[float], target_far: float) -> float:
    """Lowest score threshold t such that the fraction of impostor scores
    >= t is <= target_far -- scanning candidate thresholds from the
    impostor scores themselves (a finite set) rather than a continuous
    search, since the false-accept rate only changes at those points."""
    ordered = sorted(impostor_scores)
    n = len(ordered)
    for candidate in ordered:
        accepted = sum(1 for s in ordered if s >= candidate)
        if accepted / n <= target_far:
            return candidate
    return 1.0  # no threshold in the sample achieves target_far; require a perfect score
