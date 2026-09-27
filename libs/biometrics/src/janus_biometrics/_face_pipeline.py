from __future__ import annotations

import cv2
import numpy as np

# Shared, provider-agnostic pieces of the local:sface chain (YuNet
# detection + quality gate + SFace embedding), factored out so both the
# 1:1 provider (providers/sface.py) and the bounded low-level exception
# for libs/presence (low_level.py, requisito 8bis) reuse the exact same
# code instead of two copies drifting apart. Liveness (MiniFASNet) and
# threshold/decision logic stay out of this module: they are specific to
# the 1:1 verification path and requisito 8bis explicitly excludes them.

EMBEDDING_DIM = 128

DETECT_SCORE_THRESHOLD = 0.9
DETECT_NMS_THRESHOLD = 0.3
DETECT_TOP_K = 10

# Quality gate thresholds (requisito: control de calidad antes de puntuar).
MIN_FACE_SIZE_PX = 80
MIN_LAPLACIAN_SHARPNESS = 60.0
MIN_MEAN_LUMINANCE = 40.0
MAX_MEAN_LUMINANCE = 215.0


def decode_image(image: bytes) -> np.ndarray:
    array = np.frombuffer(image, dtype=np.uint8)
    frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Could not decode image bytes as a valid image")
    return frame


def create_detector(yunet_path: str, image_shape: tuple[int, int]) -> cv2.FaceDetectorYN:
    return cv2.FaceDetectorYN.create(
        str(yunet_path),
        "",
        (image_shape[1], image_shape[0]),
        DETECT_SCORE_THRESHOLD,
        DETECT_NMS_THRESHOLD,
        DETECT_TOP_K,
    )


def create_recognizer(sface_path: str) -> cv2.FaceRecognizerSF:
    return cv2.FaceRecognizerSF.create(str(sface_path), "")


def detect_faces(detector: cv2.FaceDetectorYN, frame: np.ndarray) -> list[np.ndarray]:
    _, detections = detector.detect(frame)
    if detections is None:
        return []
    return list(detections)


def check_quality(frame: np.ndarray, face: np.ndarray) -> tuple[bool, str]:
    x, y, w, h = face[:4].astype(int)
    x, y = max(x, 0), max(y, 0)
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        return False, "quality_crop_empty"
    if w < MIN_FACE_SIZE_PX or h < MIN_FACE_SIZE_PX:
        return False, "quality_face_too_small"

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    if sharpness < MIN_LAPLACIAN_SHARPNESS:
        return False, "quality_too_blurry"

    mean_luminance = float(gray.mean())
    if not (MIN_MEAN_LUMINANCE <= mean_luminance <= MAX_MEAN_LUMINANCE):
        return False, "quality_bad_luminance"

    return True, "ok"


def embed_face(
    recognizer: cv2.FaceRecognizerSF, frame: np.ndarray, face: np.ndarray
) -> list[float]:
    aligned = recognizer.alignCrop(frame, face)
    feature = recognizer.feature(aligned)
    embedding = feature.flatten().astype(float).tolist()
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"Expected {EMBEDDING_DIM}-dim embedding, got {len(embedding)}")
    return embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.array(a), np.array(b)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)
