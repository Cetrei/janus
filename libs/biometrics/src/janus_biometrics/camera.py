"""Live camera capture, multi-camera and cross-platform by design.

Separate from _face_pipeline.py on purpose: this module only opens
devices and reads frames, it knows nothing about YuNet/SFace/MiniFASNet.
That split is what lets libs/presence reuse this for its own multi-camera
requirement (see libs/presence/SPEC.md) without pulling in any of the 1:1
verification code, and lets manual_camera_check.py (or any future preview
tool) reuse it without duplicating platform-specific VideoCapture backend
selection.

Requires the `face-gui` extra (opencv-python, not opencv-python-headless):
opencv-python-headless has no GUI support and, on Linux, many PyPI wheels
also ship without V4L2 capture enabled. Production code paths
(providers/sface.py, low_level.py) only need `face` (headless) and must
never import this module, so a headless-only install of janus_biometrics
stays fully functional without ever touching camera.py.

CameraUnavailable/CameraReadError (below) also inherit from
janus_biometrics.errors.SensorUnavailable (requisito 20/22's canonical
sensor error), on top of their own local CameraError hierarchy. This is
deliberately dual: manual_camera_check.py and any other camera.py-specific
caller keep catching CameraError/CameraUnavailable/CameraReadError by name
for their own detailed handling (index, hint text), while sensors.py's
SensorSource.capture_frame() (the ABC consumed by BiometricService) only
needs to catch the one canonical SensorUnavailable to satisfy requisito 20
without camera.py needing to import sensors.py or know it exists.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

import cv2

from janus_biometrics.errors import SensorUnavailable


# Backend selection is the actual fix for the Linux "can't open camera by
# index" failure: cv2.VideoCapture(0) with no backend argument on Linux
# tries V4L2 by default, but some opencv builds/systems need it requested
# explicitly rather than left to auto-detection, and silently fail
# otherwise rather than raising. Windows needs DirectShow (CAP_DSHOW);
# MSMF (the other native Windows backend) is more failure-prone for
# capture-after-close cycles like enroll's multi-capture loop, per
# long-standing OpenCV bug reports, so DirectShow is preferred deliberately.
def _platform_backend() -> int:
    system = platform.system()
    if system == "Linux":
        return cv2.CAP_V4L2
    if system == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY  # macOS and anything else: let OpenCV pick (AVFoundation)


_MAX_PROBE_INDEX = 8  # how many device indices to check when listing cameras

# Requested capture resolution: cameras vary a lot in their native/default
# resolution (this repo's own dev machine defaults to 640x360 on its
# integrated webcam), and a low default resolution directly hurts face
# quality gating (_face_pipeline.MIN_FACE_SIZE_FRAC is relative to frame
# size, but a smaller frame still means less real detail per face for
# SFace/MiniFASNet). Requesting a higher resolution costs nothing when the
# device can't deliver it: V4L2/DirectShow both fall back to the closest
# mode they support, so this is a best-effort upgrade, never a requirement.
_PREFERRED_WIDTH = 1280
_PREFERRED_HEIGHT = 720

# Requested pixel format (FourCC). Not previously set anywhere in this
# module -- Camera.open()/list_cameras() left the format entirely up to
# whatever the driver defaults to, which is a likely root cause of the
# monochrome-looking, flickering preview reported against real hardware
# (see AGENT.md's "verify corrido de nuevo" entry and the biometrics
# camera/detector investigation handoff): some V4L2 devices default to a
# YUYV or greyscale-only mode, or switch formats/framerates under the hood
# depending on what a generic capture request negotiates, and OpenCV then
# converts that unexpected format to BGR with visibly wrong results.
# MJPG is requested explicitly because it is the most broadly supported
# color format across both V4L2 (Linux) and DirectShow (Windows) webcams
# at 720p, and, unlike raw YUYV, doesn't force USB bandwidth constraints
# that make many webcams fall back to a lower framerate or resolution.
# Same best-effort contract as _PREFERRED_WIDTH/_PREFERRED_HEIGHT above:
# cap.set() for FOURCC commonly returns True even when the request is
# ignored, so this is requested, never assumed granted -- if the flicker
# or monochrome look persists after this change, the next diagnostic step
# (not yet done, needs real hardware) is `v4l2-ctl --device=/dev/videoN
# --list-ctrls` / `v4l2-ctl --list-formats-ext` to see what the device
# actually negotiated, per the handoff notes -- do not guess further
# fixes here without that real output.
_PREFERRED_FOURCC = cv2.VideoWriter_fourcc(*"MJPG")


@dataclass(frozen=True)
class CameraInfo:
    """One discoverable camera. `index` is what OpenCV needs to open it;
    `label` is best-effort (OpenCV cannot read a real device name on most
    backends, so this is a positional placeholder, not a hardware name)."""

    index: int
    label: str
    width: int
    height: int


def list_cameras(max_index: int = _MAX_PROBE_INDEX) -> list[CameraInfo]:
    """Probes device indices 0..max_index-1 and returns the ones that
    actually open and deliver a frame. This is a real probe (opens each
    device briefly), not a directory listing, because neither Linux nor
    Windows expose a reliable index-to-name mapping through OpenCV itself;
    a fast /dev/video* scan would also list indices that open but never
    deliver a frame (metadata-only V4L2 nodes are common on Linux webcams
    that expose more than one device node per physical camera).
    """
    backend = _platform_backend()
    found: list[CameraInfo] = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index, backend)
        try:
            if not cap.isOpened():
                continue
            # Match what Camera.open() will actually request, so `list`
            # reports the resolution/format enroll/verify will really
            # capture at, not whatever lower default the device starts at.
            cap.set(cv2.CAP_PROP_FOURCC, _PREFERRED_FOURCC)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, _PREFERRED_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _PREFERRED_HEIGHT)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            found.append(
                CameraInfo(index=index, label=f"Camera {index}", width=width, height=height)
            )
        finally:
            cap.release()
    return found


class Camera:
    """One open camera device. Multi-camera support (per libs/presence's
    spec) is just: construct more than one Camera with different indices;
    this class deliberately holds no global/singleton state so several
    instances can coexist.
    """

    def __init__(self, index: int = 0) -> None:
        self._index = index
        self._backend = _platform_backend()
        self._cap: cv2.VideoCapture | None = None

    @property
    def index(self) -> int:
        return self._index

    def open(self) -> None:
        if self._cap is not None:
            return
        cap = cv2.VideoCapture(self._index, self._backend)
        if not cap.isOpened():
            cap.release()
            raise CameraUnavailable(self._index, _platform_hint())
        # Best-effort: ask for a higher resolution than whatever the
        # device's own default is. cv2.VideoCapture.set() on V4L2/DSHOW
        # commonly returns True even when the request is ignored or only
        # partially honored, so this never raises -- callers should read
        # the actual frame shape from the first read() rather than assume
        # _PREFERRED_WIDTH/_PREFERRED_HEIGHT were granted.
        # FourCC must be set before resolution on most backends (V4L2
        # especially): the driver picks its supported resolution list
        # based on the active pixel format, so setting format first avoids
        # a resolution request silently applying to the wrong format.
        cap.set(cv2.CAP_PROP_FOURCC, _PREFERRED_FOURCC)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, _PREFERRED_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _PREFERRED_HEIGHT)
        self._cap = cap

    def read(self):  # -> np.ndarray (BGR frame)
        """Reads one frame. Raises CameraReadError on a failed read rather
        than returning None, so callers (preview loops especially) can't
        silently treat a dropped frame as "nothing changed"."""
        if self._cap is None:
            raise RuntimeError("Camera.read() called before open()")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraReadError(self._index)
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class CameraError(Exception):
    """Base error for camera.py."""


class CameraUnavailable(CameraError, SensorUnavailable):
    def __init__(self, index: int, hint: str) -> None:
        # Two parallel __init__ chains (CameraError via Exception, and
        # SensorUnavailable via BiometricsError) can't both run through
        # super().__init__ without MRO surprises, so this calls
        # Exception.__init__ directly with the detailed camera.py-specific
        # message, then sets the fields SensorUnavailable's own callers
        # expect (sensor_id, reason) so `except SensorUnavailable as e:
        # e.sensor_id` works uniformly across camera.py and any future
        # SensorSource implementation (e.g. MicrophoneSource).
        message = f"Could not open camera index {index}. {hint}"
        Exception.__init__(self, message)
        self.index = index
        self.sensor_id = str(index)
        self.reason = hint


class CameraReadError(CameraError, SensorUnavailable):
    def __init__(self, index: int) -> None:
        reason = "device may have been disconnected or is in use by another app"
        message = f"Camera index {index} opened but a frame read failed ({reason})."
        Exception.__init__(self, message)
        self.index = index
        self.sensor_id = str(index)
        self.reason = reason


def _platform_hint() -> str:
    system = platform.system()
    if system == "Linux":
        return (
            "On Linux: check `ls /dev/video*` exists, that your user is in "
            "the `video` group (`groups $USER`; `sudo usermod -aG video "
            "$USER` then re-login if not), and that no other app "
            "(browser tab, another script) is already holding the device."
        )
    if system == "Windows":
        return (
            "On Windows: check Settings > Privacy & security > Camera "
            "allows desktop apps, and that no other app is already using "
            "the camera."
        )
    return "Check the camera is connected and not in use by another app."


def print_camera_list(cameras: list[CameraInfo], *, file=sys.stdout) -> None:
    if not cameras:
        print(f"No cameras found (probed indices 0-{_MAX_PROBE_INDEX - 1}).", file=file)
        return
    print(f"Found {len(cameras)} camera(s):", file=file)
    for cam in cameras:
        print(f"  [{cam.index}] {cam.label} ({cam.width}x{cam.height})", file=file)
