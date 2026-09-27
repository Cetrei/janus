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

# Lowered from 0.9 (2026-09-26): 0.9 is on the strict end for YuNet (its
# own opencv_zoo examples commonly use 0.6-0.9), and strict thresholds hurt
# detection at head tilt/profile angles specifically -- a partially-occluded
# or angled face produces a lower-confidence score even when it is a real,
# usable detection. Tried before reaching for a different detector (SCRFD)
# per spec-18's investigation notes: cheap, zero new dependencies, zero
# license question. Not yet confirmed by execution (no camera access this
# session) -- if profile/tilted detection is still poor after this change,
# that is evidence YuNet's architecture (not just this threshold) is the
# limit, and SCRFD (local:scrfd, see providers/scrfd.py) is the fallback.
DETECT_SCORE_THRESHOLD = 0.6
DETECT_NMS_THRESHOLD = 0.3
DETECT_TOP_K = 10

# Quality gate thresholds (requisito: control de calidad antes de puntuar).
#
# MIN_FACE_SIZE_FRAC is relative to frame height, not an absolute pixel
# count: cameras used against this pipeline (webcam, garden/room fixed
# cameras via libs/presence) vary wildly in native resolution and in
# subject distance, and neither is under this library's control. An
# absolute-pixel floor silently rejects real, usable faces on a
# low-resolution camera (e.g. 640x360) at a completely normal distance,
# while doing nothing useful on a high-resolution one. What actually
# matters for SFace/MiniFASNet is the *fraction of the frame* the face
# occupies, since that tracks how much real detail is available
# regardless of source resolution. 0.10 (10% of frame height) is the
# floor below which SFace's own accuracy claims and MiniFASNet liveness
# both start to degrade for lack of real detail in the crop.
MIN_FACE_SIZE_FRAC = 0.10
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


# --- SCRFD detector (opt-in alternative to YuNet, see providers/scrfd.py) ---
#
# OpenCV has no built-in wrapper for SCRFD (unlike YuNet's cv2.FaceDetectorYN),
# so this is a raw onnxruntime session plus manual anchor decoding. The decode
# logic below is a direct port of the official InsightFace inference code
# (deepinsight/insightface, python-package/insightface/model_zoo/scrfd.py,
# also mirrored verbatim in numerous downstream projects), not a
# reconstruction from a description -- same discipline as
# crop_with_margin's port of the MiniFASNet crop geometry, after that
# lesson was learned the hard way (see AGENT.md history: two attempts on
# the crop before reading the real source). If detection quality looks
# wrong, re-check against that source before adjusting constants here.
_SCRFD_INPUT_SIZE = 640  # scrfd_10g_bnkps.onnx: fixed square input, letterboxed
_SCRFD_STRIDES = (8, 16, 32)  # 3 feature maps, matches the 9-output bnkps export
_SCRFD_NUM_ANCHORS = 2  # per anchor location, for the bnkps export (fmc=3, use_kps=True)
_SCRFD_INPUT_MEAN = 127.5
_SCRFD_INPUT_STD = 128.0
_SCRFD_NMS_THRESHOLD = 0.4


def create_scrfd_session(scrfd_path: str):
    """Creates the onnxruntime session for SCRFD. Returned separately from
    detect_faces_scrfd (rather than hidden inside it) so callers manage its
    lifetime the same way providers/sface.py already manages YuNet/SFace/
    MiniFASNet sessions (load once, reuse across frames)."""
    import onnxruntime  # local import: optional face extra, same as sface.py

    return onnxruntime.InferenceSession(str(scrfd_path))


def _scrfd_distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """Port of insightface's distance2bbox: decodes the 4 predicted
    distances (left, top, right, bottom) from each anchor center into an
    (x1, y1, x2, y2) box."""
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _scrfd_distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """Port of insightface's distance2kps: decodes 5 predicted (dx, dy)
    keypoint offsets per anchor into absolute (x, y) landmark positions."""
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, i % 2] + distance[:, i]
        py = points[:, i % 2 + 1] + distance[:, i + 1]
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)


def _scrfd_nms(dets: np.ndarray, thresh: float) -> list[int]:
    """Port of insightface's greedy NMS (its own hand-rolled
    implementation, not cv2.dnn.NMSBoxes -- kept identical rather than
    swapped for an OpenCV equivalent, to avoid a subtly different keep
    order/tie-breaking changing which face survives)."""
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]
    return keep


def detect_faces_scrfd(
    session, frame: np.ndarray, threshold: float = DETECT_SCORE_THRESHOLD
) -> list[np.ndarray]:
    """Runs SCRFD detection and returns faces in the same shape
    detect_faces() (YuNet) returns: a list of arrays where face[:4] is
    (x, y, w, h) in pixel coords of the original frame and face[4:14] are
    5 (x, y) keypoints -- so callers (check_quality, embed_face,
    crop_with_margin) work unmodified regardless of which detector ran.
    SCRFD itself outputs (x1, y1, x2, y2) boxes; the conversion to (x, y,
    w, h) happens at the end of this function, not upstream, to keep the
    port of insightface's own decode math untouched.

    Letterboxing (resize preserving aspect ratio, pad to a square input)
    follows insightface's own SCRFD.detect(), not a naive full-frame
    resize/stretch, since the model was trained on letterboxed input.
    """
    input_size = _SCRFD_INPUT_SIZE
    frame_h, frame_w = frame.shape[:2]
    im_ratio = frame_h / frame_w
    if im_ratio > 1.0:
        new_height = input_size
        new_width = int(new_height / im_ratio)
    else:
        new_width = input_size
        new_height = int(new_width * im_ratio)
    det_scale = new_height / frame_h
    resized = cv2.resize(frame, (new_width, new_height))
    det_img = np.zeros((input_size, input_size, 3), dtype=np.uint8)
    det_img[:new_height, :new_width, :] = resized

    blob = cv2.dnn.blobFromImage(
        det_img,
        1.0 / _SCRFD_INPUT_STD,
        (input_size, input_size),
        (_SCRFD_INPUT_MEAN, _SCRFD_INPUT_MEAN, _SCRFD_INPUT_MEAN),
        swapRB=True,
    )
    output_names = [o.name for o in session.get_outputs()]
    net_outs = session.run(output_names, {session.get_inputs()[0].name: blob})

    scores_list, bboxes_list, kpss_list = [], [], []
    fmc = len(_SCRFD_STRIDES)
    for idx, stride in enumerate(_SCRFD_STRIDES):
        scores = net_outs[idx]
        bbox_preds = net_outs[idx + fmc] * stride
        kps_preds = net_outs[idx + fmc * 2] * stride

        height, width = input_size // stride, input_size // stride
        anchor_centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
        anchor_centers = (anchor_centers * stride).reshape((-1, 2))
        if _SCRFD_NUM_ANCHORS > 1:
            anchor_centers = np.stack(
                [anchor_centers] * _SCRFD_NUM_ANCHORS, axis=1
            ).reshape((-1, 2))

        pos_inds = np.where(scores.ravel() >= threshold)[0]
        bboxes = _scrfd_distance2bbox(anchor_centers, bbox_preds)
        kpss = _scrfd_distance2kps(anchor_centers, kps_preds).reshape((-1, 5, 2))

        scores_list.append(scores.ravel()[pos_inds])
        bboxes_list.append(bboxes[pos_inds])
        kpss_list.append(kpss[pos_inds])

    if not any(s.size for s in scores_list):
        return []

    scores_all = np.concatenate(scores_list)
    bboxes_all = np.concatenate(bboxes_list) / det_scale
    kpss_all = np.concatenate(kpss_list) / det_scale

    order = scores_all.argsort()[::-1]
    pre_det = np.hstack((bboxes_all, scores_all[:, None])).astype(np.float32)[order]
    kpss_ordered = kpss_all[order]
    keep = _scrfd_nms(pre_det, _SCRFD_NMS_THRESHOLD)

    faces = []
    for i in keep:
        x1, y1, x2, y2, score = pre_det[i]
        w, h = x2 - x1, y2 - y1
        # face[:4]=(x,y,w,h), face[4:14]=5 keypoints flattened, face[14]=score:
        # matches cv2.FaceDetectorYN's own output layout so downstream code
        # (check_quality, embed_face's alignCrop, crop_with_margin) is
        # detector-agnostic.
        row = [x1, y1, w, h, *kpss_ordered[i].reshape(-1).tolist(), score]
        faces.append(np.array(row, dtype=np.float32))
    return faces


# CAVEAT (unconfirmed by execution, same discipline as crop_with_margin's
# own CAVEAT above): embed_face() below calls cv2.FaceRecognizerSF.alignCrop,
# which was written for cv2.FaceDetectorYN's own 5-keypoint output. SCRFD's
# 5 keypoints (left eye, right eye, nose, left mouth corner, right mouth
# corner) follow the same widely-documented RetinaFace convention YuNet
# itself uses, so alignCrop is expected to accept detect_faces_scrfd's
# output directly without reordering -- but this has not been confirmed by
# running alignCrop against real SCRFD keypoints in this session (no
# camera/shell access). If verify() produces visibly misaligned crops or a
# degraded embedding with local:scrfd specifically (not local:sface), check
# keypoint order here first before assuming the model itself is at fault.


def check_quality(frame: np.ndarray, face: np.ndarray) -> tuple[bool, str]:
    x, y, w, h = face[:4].astype(int)
    x, y = max(x, 0), max(y, 0)
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        return False, "quality_crop_empty"
    frame_h = frame.shape[0]
    min_face_px = frame_h * MIN_FACE_SIZE_FRAC
    if w < min_face_px or h < min_face_px:
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


# MiniFASNet liveness scale factors. Confirmed directly against the
# upstream source (minivision-ai/Silent-Face-Anti-Spoofing,
# src/generate_patches.py's CropImage._get_new_box/crop, and the weight
# filenames themselves under resources/anti_spoof_models/): each model was
# trained on a crop expanded around the face bbox at its own scale factor,
# not the tight bbox itself, because the liveness signal (skin texture vs.
# print/screen artifacts, moire, photo edges) depends on context around
# the face, not just the face region. Passing the tight bbox crop (this
# pipeline's original behavior) starves the model of that context and
# produces false FAILs on real faces -- confirmed in manual testing (HIGH
# decision, FAIL liveness, confirmed real person) before this fix, and
# still FAIL after a first attempt at this fix that used the wrong
# geometry (see below).
#
# The two models do NOT share a scale factor -- confirmed by reading the
# actual weight filenames on disk:
#   resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth
#   resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth
# Per src/utility.py's own parse_model_name (`scale = float(info[0])`,
# the first underscore-separated segment of the filename), V2's scale is
# 2.7 and V1SE's is 4.0 -- an earlier version of this code guessed V1SE
# also used 2.7, which was wrong and unconfirmed; this is now read off the
# real filenames, not guessed.
MINIFASNET_SCALE_V2 = 2.7
MINIFASNET_SCALE_V1SE = 4.0


def crop_with_margin(frame: np.ndarray, face: np.ndarray, scale: float) -> np.ndarray:
    """Crops the region MiniFASNet expects around a detected face, at the
    given `scale`. This is a direct port of `CropImage._get_new_box` +
    `CropImage.crop` from minivision-ai/Silent-Face-Anti-Spoofing's
    src/generate_patches.py (read from the real upstream source, not
    reconstructed from a description) -- two details matter and an
    earlier version of this function got both wrong:

    1. The crop is NOT a square. Width and height are each independently
       `bbox_w * scale` / `bbox_h * scale`, centered on the bbox center --
       so a non-square face bbox produces a non-square crop, matching
       what the model was actually trained on.
    2. Out-of-frame handling is a SHIFT, not a clip. If the expanded box
       would fall outside the frame on one side, the whole box is shifted
       back into bounds (keeping its full requested size) rather than
       truncated -- clipping silently shrinks the crop below what the
       model expects, which a resize-to-80x80 afterward would hide rather
       than surface.

    `scale` is also capped against how much room the frame actually has
    around the bbox (`min((frame_h-1)/box_h, (frame_w-1)/box_w, scale)`,
    same as upstream), so a face that fills nearly the whole frame doesn't
    request an expansion larger than the frame itself.
    """
    x, y, w, h = (float(v) for v in face[:4])
    frame_h, frame_w = frame.shape[:2]

    effective_scale = min((frame_h - 1) / h, (frame_w - 1) / w, scale)
    new_w = w * effective_scale
    new_h = h * effective_scale
    cx, cy = x + w / 2.0, y + h / 2.0

    x0 = cx - new_w / 2.0
    y0 = cy - new_h / 2.0
    x1 = cx + new_w / 2.0
    y1 = cy + new_h / 2.0

    if x0 < 0:
        x1 -= x0
        x0 = 0
    if y0 < 0:
        y1 -= y0
        y0 = 0
    if x1 > frame_w - 1:
        x0 -= x1 - frame_w + 1
        x1 = frame_w - 1
    if y1 > frame_h - 1:
        y0 -= y1 - frame_h + 1
        y1 = frame_h - 1

    ix0, iy0, ix1, iy1 = int(x0), int(y0), int(x1), int(y1)
    crop = frame[iy0 : iy1 + 1, ix0 : ix1 + 1]
    if crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
        raise ValueError(
            "crop_with_margin: expanded crop is empty/degenerate (face "
            "too large relative to frame, or bbox coordinates invalid)"
        )
    return crop
