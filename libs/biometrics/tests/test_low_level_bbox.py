from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2", reason="opencv-python-headless not installed (face extra)")

from janus_biometrics import _face_pipeline as pipeline  # noqa: E402
from janus_biometrics import low_level  # noqa: E402
from janus_biometrics.base import FaceEmbedding  # noqa: E402
from janus_biometrics.low_level import FaceEmbedder  # noqa: E402

FRAME_HEIGHT = 240
FRAME_WIDTH = 320
EMBEDDING = [0.1] * 128


class FakeModelCache:
    def resolve(self, model_id: str) -> Path:
        return Path(f"/fake/{model_id}.onnx")


def make_face(x: float, y: float, w: float, h: float) -> np.ndarray:
    return np.array([x, y, w, h, *([0.0] * 11)], dtype=np.float32)


@pytest.fixture
def frame() -> np.ndarray:
    return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)


def patch_pipeline(monkeypatch: pytest.MonkeyPatch, frame: np.ndarray, faces: list) -> None:
    monkeypatch.setattr(pipeline, "decode_image", lambda image: frame)
    monkeypatch.setattr(pipeline, "create_detector", lambda path, shape: object())
    monkeypatch.setattr(pipeline, "fit_detector_input", lambda detector, shape: None)
    monkeypatch.setattr(pipeline, "create_recognizer", lambda path: object())
    monkeypatch.setattr(pipeline, "detect_faces", lambda detector, image: faces)
    monkeypatch.setattr(pipeline, "check_quality", lambda image, face: (True, "ok"))
    monkeypatch.setattr(pipeline, "embed_face", lambda recognizer, image, face: EMBEDDING)


def test_should_default_bbox_to_none() -> None:
    result = FaceEmbedding(embedding=EMBEDDING, quality_ok=True)

    assert result.bbox is None


def test_should_return_bbox_as_int_tuple(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(10.4, 20.6, 50.2, 60.7)])

    results = low_level.detect_and_embed_faces(b"", FakeModelCache())

    assert results[0].bbox == (10, 21, 50, 61)
    assert all(isinstance(v, int) for v in results[0].bbox)


def test_should_return_one_bbox_per_face(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    faces = [make_face(10, 10, 40, 40), make_face(200, 100, 50, 50)]
    patch_pipeline(monkeypatch, frame, faces)

    results = low_level.detect_and_embed_faces(b"", FakeModelCache())

    assert [r.bbox for r in results] == [(10, 10, 40, 40), (200, 100, 50, 50)]


def test_should_clamp_bbox_hanging_over_top_left_edge(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(-15, -10, 60, 50)])

    results = low_level.detect_and_embed_faces(b"", FakeModelCache())

    assert results[0].bbox == (0, 0, 45, 40)


def test_should_clamp_bbox_hanging_over_bottom_right_edge(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(300, 220, 60, 50)])

    results = low_level.detect_and_embed_faces(b"", FakeModelCache())

    assert results[0].bbox == (300, 220, 20, 20)


def test_should_return_zero_size_bbox_when_face_is_fully_outside(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(400, 300, 30, 30)])

    results = low_level.detect_and_embed_faces(b"", FakeModelCache())

    x, y, w, h = results[0].bbox
    assert w == 0 or h == 0


def test_should_keep_embedding_and_quality_alongside_bbox(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(10, 10, 40, 40)])

    results = low_level.detect_and_embed_faces(b"", FakeModelCache())

    assert results[0].embedding == EMBEDDING
    assert results[0].quality_ok is True


class RecordingModelCache(FakeModelCache):
    def __init__(self) -> None:
        self.resolved: list[str] = []

    def resolve(self, model_id: str) -> Path:
        self.resolved.append(model_id)
        return super().resolve(model_id)


def test_should_resolve_and_build_models_once_across_many_embeds(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(10, 10, 40, 40)])
    detectors_built: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "create_detector",
        lambda path, shape: detectors_built.append(path) or object(),
    )
    cache = RecordingModelCache()

    embedder = FaceEmbedder(cache)
    for _ in range(3):
        embedder.embed(b"")

    assert cache.resolved == ["yunet", "sface"]
    assert len(detectors_built) == 1


def test_should_refit_detector_only_when_the_frame_shape_changes(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(10, 10, 40, 40)])
    small = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    large = np.zeros((480, 640, 3), dtype=np.uint8)
    frames = iter([small, small, large, large, small])
    fitted: list[tuple[int, int]] = []
    monkeypatch.setattr(pipeline, "decode_image", lambda image: next(frames))
    monkeypatch.setattr(
        pipeline, "fit_detector_input", lambda detector, shape: fitted.append(shape)
    )
    embedder = FaceEmbedder(FakeModelCache())

    for _ in range(5):
        embedder.embed(b"")

    assert fitted == [(480, 640), (FRAME_HEIGHT, FRAME_WIDTH)]


def test_should_refuse_to_embed_after_close(
    monkeypatch: pytest.MonkeyPatch, frame: np.ndarray
) -> None:
    patch_pipeline(monkeypatch, frame, [make_face(10, 10, 40, 40)])
    embedder = FaceEmbedder(FakeModelCache())

    embedder.close()

    with pytest.raises(RuntimeError):
        embedder.embed(b"")
