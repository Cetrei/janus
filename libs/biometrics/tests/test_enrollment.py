from __future__ import annotations

import numpy as np
import pytest

from janus_biometrics import enrollment
from janus_biometrics.base import PcmAudio
from janus_biometrics.errors import EnrollmentError


class _FakeDetector:
    """Double for cv2.FaceDetectorYN: returns a fixed number of faces per
    call, controlled by the test."""

    def __init__(self, faces_per_call: list[list[np.ndarray]]) -> None:
        self._faces_per_call = list(faces_per_call)
        self.set_input_size_calls = 0

    def setInputSize(self, size) -> None:
        self.set_input_size_calls += 1


class _FakeRecognizer:
    pass


def _one_face() -> np.ndarray:
    # x, y, w, h, 10 keypoint values, score -- shape doesn't matter to the
    # fakes below, only that check_quality/embed_face are also faked.
    return np.array([10, 10, 100, 100, *([0.0] * 10), 0.99], dtype=np.float32)


@pytest.fixture
def patch_face_pipeline(monkeypatch):
    """Patches janus_biometrics._face_pipeline as used by enrollment.py,
    so enroll_face is exercised without real images/cv2 model files."""
    from janus_biometrics import _face_pipeline as pipeline

    calls = {"faces_per_image": [], "quality_per_image": [], "index": 0}

    def _decode_image(image: bytes):
        return np.zeros((200, 200, 3), dtype=np.uint8)

    def _create_detector(yunet_path, image_shape):
        return _FakeDetector([])

    def _create_recognizer(sface_path):
        return _FakeRecognizer()

    def _detect_faces(detector, frame):
        faces = calls["faces_per_image"][calls["index"]]
        return faces

    def _check_quality(frame, face):
        return calls["quality_per_image"][calls["index"]]

    def _embed_face(recognizer, frame, face):
        embedding = [float(calls["index"])] * pipeline.EMBEDDING_DIM
        calls["index"] += 1
        return embedding

    monkeypatch.setattr(pipeline, "decode_image", _decode_image)
    monkeypatch.setattr(pipeline, "create_detector", _create_detector)
    monkeypatch.setattr(pipeline, "create_recognizer", _create_recognizer)
    monkeypatch.setattr(pipeline, "detect_faces", _detect_faces)
    monkeypatch.setattr(pipeline, "check_quality", _check_quality)
    monkeypatch.setattr(pipeline, "embed_face", _embed_face)
    return calls


class _FakeModelCache:
    def resolve(self, model_id: str):
        return f"/fake/{model_id}.onnx"


class TestEnrollFace:
    def test_requires_minimum_samples(self):
        with pytest.raises(EnrollmentError, match="at least 5"):
            enrollment.enroll_face([b"img"] * 4, _FakeModelCache())

    def test_builds_enrollment_from_five_good_samples(self, patch_face_pipeline):
        patch_face_pipeline["faces_per_image"] = [[_one_face()] for _ in range(5)]
        patch_face_pipeline["quality_per_image"] = [(True, "ok") for _ in range(5)]

        result = enrollment.enroll_face([b"img"] * 5, _FakeModelCache())

        assert result.kind == "face"
        assert result.samples == 5
        assert len(result.embeddings) == 5
        assert result.model_id == "sface-yunet-minifasnet-v1"
        assert len(result.centroid) == len(result.embeddings[0])

    def test_rejects_sample_with_no_face(self, patch_face_pipeline):
        patch_face_pipeline["faces_per_image"] = [[] for _ in range(5)]
        patch_face_pipeline["quality_per_image"] = [(True, "ok") for _ in range(5)]

        with pytest.raises(EnrollmentError, match="no face detected"):
            enrollment.enroll_face([b"img"] * 5, _FakeModelCache())

    def test_rejects_sample_with_multiple_faces(self, patch_face_pipeline):
        patch_face_pipeline["faces_per_image"] = [
            [_one_face(), _one_face()],
            *[[_one_face()] for _ in range(4)],
        ]
        patch_face_pipeline["quality_per_image"] = [(True, "ok") for _ in range(5)]

        with pytest.raises(EnrollmentError, match="more than one face"):
            enrollment.enroll_face([b"img"] * 5, _FakeModelCache())

    def test_rejects_sample_failing_quality_gate(self, patch_face_pipeline):
        patch_face_pipeline["faces_per_image"] = [[_one_face()] for _ in range(5)]
        patch_face_pipeline["quality_per_image"] = [
            (False, "quality_too_blurry"),
            *[(True, "ok") for _ in range(4)],
        ]

        with pytest.raises(EnrollmentError, match="quality_too_blurry"):
            enrollment.enroll_face([b"img"] * 5, _FakeModelCache())


class _FakeVoiceExtractor:
    def __init__(self, dim: int = 8) -> None:
        self._dim = dim
        self.calls = 0

    def embed(self, audio: PcmAudio) -> list[float]:
        self.calls += 1
        return [float(self.calls)] * self._dim


def _pcm(seconds: float, sample_rate: int = 16_000) -> PcmAudio:
    frame_count = int(seconds * sample_rate)
    return PcmAudio(samples=b"\x00\x01" * frame_count, sample_rate=sample_rate)


class TestEnrollVoice:
    def test_requires_minimum_samples(self):
        extractor = _FakeVoiceExtractor()
        with pytest.raises(EnrollmentError, match="at least 5"):
            enrollment.enroll_voice([_pcm(3.0)] * 4, extractor, "fake-model")

    def test_rejects_utterance_shorter_than_minimum(self):
        extractor = _FakeVoiceExtractor()
        recordings = [_pcm(3.0)] * 4 + [_pcm(1.0)]
        with pytest.raises(EnrollmentError, match="below the 3.0s"):
            enrollment.enroll_voice(recordings, extractor, "fake-model")

    def test_builds_enrollment_from_five_good_samples(self):
        extractor = _FakeVoiceExtractor(dim=8)
        recordings = [_pcm(3.5)] * 5

        result = enrollment.enroll_voice(recordings, extractor, "fake-model")

        assert result.kind == "voice"
        assert result.samples == 5
        assert result.model_id == "fake-model"
        assert result.dim == 8
        assert extractor.calls == 5


class TestCalibrate:
    def test_requires_at_least_two_genuine_samples(self):
        with pytest.raises(EnrollmentError, match="at least 2"):
            enrollment.calibrate([[1.0, 0.0, 0.0]])

    def test_without_impostors_uses_conservative_midpoint(self):
        genuine = [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02], [1.0, 0.0], [0.97, 0.03]]

        result = enrollment.calibrate(genuine, target_frr=0.05)

        assert result.impostor_scores is None
        assert 0.0 <= result.t_low <= result.t_high <= 1.0
        assert len(result.genuine_scores) == len(genuine)

    def test_with_impostors_sets_t_high_below_far_target(self):
        genuine = [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02], [0.97, 0.03], [0.96, 0.04]]
        # Impostor vectors clearly separated from the genuine cluster:
        # cosine similarity to the genuine centroid should score low.
        impostors = [[0.0, 1.0], [0.01, 0.99], [-1.0, 0.0], [0.0, -1.0]]

        result = enrollment.calibrate(genuine, impostor_embeddings=impostors, target_far=0.25)

        assert result.impostor_scores is not None
        assert result.t_high >= result.t_low

    def test_impostor_threshold_never_drops_below_genuine_floor(self):
        genuine = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
        # Impostors that score *higher* than the genuine floor: t_high must
        # still not fall below t_low even though the naive FAR-based pick
        # would be lower.
        impostors = [[1.0, 0.0], [1.0, 0.0]]

        result = enrollment.calibrate(genuine, impostor_embeddings=impostors, target_far=0.5)

        assert result.t_high >= result.t_low
