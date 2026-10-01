"""Persistent camera sources (SPEC.md ampliación, requisito 21).

`LocalCameraSource` (frame_source.py) opens the device, reads one frame and
releases it on every call. That is fine for a one off capture, but a monitor
sampling several times a second would pay the open cost each time, and the
first frames after opening are often dark while auto exposure settles.
`PersistentCameraSource` keeps each device open between captures instead.

It gives the monitor one rule for recovery: any failure closes the device, so
the next capture opens it again from scratch. It never retries on its own;
when to try again is the monitor's backoff, not this module's.

Local cameras reuse `janus_biometrics.camera.Camera` (requisito 21). Streams
(`rtsp`) go through the small `UrlCamera` below, which has the same
open/read/close shape. `mcp` sources are not handled here: they need a tool
injected by Janus (requisito 10).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from typing import Protocol

from janus_presence.errors import PresenceUnavailableError
from janus_presence.models import SourceConfig, SourceKind, SourceLocation

__all__ = [
    "CameraDevice",
    "PersistentCameraSource",
    "UrlCamera",
    "enabled_cameras",
    "encode_jpeg",
    "open_camera_device",
]

_log = logging.getLogger(__name__)

_STREAM_RESOURCE = "camera:stream"


class CameraDevice(Protocol):
    """What a persistent source needs from a capture device. `read` returns
    one BGR frame (a numpy array) or raises."""

    def open(self) -> None: ...

    def read(self): ...

    def close(self) -> None: ...


CameraOpener = Callable[[SourceConfig], CameraDevice]
FrameEncoder = Callable[[object], bytes]


class UrlCamera:
    """A network stream (RTSP or HTTP) read through OpenCV.

    Its errors never mention the URL: stream URLs usually carry the camera's
    user and password, and errors end up in logs.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._capture = None

    def open(self) -> None:
        if self._capture is not None:
            return
        import cv2

        capture = cv2.VideoCapture(self._url)
        if not capture.isOpened():
            capture.release()
            raise PresenceUnavailableError(
                _STREAM_RESOURCE, "could not open the configured stream"
            )
        self._capture = capture

    def read(self):
        if self._capture is None:
            raise RuntimeError("UrlCamera.read() called before open()")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise PresenceUnavailableError(_STREAM_RESOURCE, "the stream returned no frame")
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def open_camera_device(config: SourceConfig) -> CameraDevice:
    """Builds, without opening, the device for one configured camera. The
    imports are lazy so this module loads without OpenCV installed."""
    if config.source == SourceLocation.RTSP:
        return UrlCamera(config.device)
    from janus_biometrics.camera import Camera

    return Camera(index=int(config.device))


def encode_jpeg(frame) -> bytes:
    """JPEG bytes of one BGR frame, the shape every FrameSource hands over."""
    import cv2

    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        raise ValueError("could not encode the frame as JPEG")
    return encoded.tobytes()


def enabled_cameras(configs: Iterable[SourceConfig]) -> list[SourceConfig]:
    return [c for c in configs if c.kind == SourceKind.CAMERA and c.enabled]


def _reason(exc: Exception) -> str:
    return getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}"


class PersistentCameraSource:
    """FrameSource over several configured cameras, each kept open between
    captures. Thread safe per camera: two threads asking for the same camera
    take turns, different cameras never wait for each other."""

    def __init__(
        self,
        configs: Iterable[SourceConfig],
        opener: CameraOpener = open_camera_device,
        encoder: FrameEncoder = encode_jpeg,
    ) -> None:
        self._configs = {config.source_id: config for config in configs}
        self._opener = opener
        self._encoder = encoder
        self._devices: dict[str, CameraDevice] = {}
        self._locks = {source_id: threading.Lock() for source_id in self._configs}

    def capture_frame(self, camera_id: str) -> bytes:
        config = self._configs.get(camera_id)
        if config is None:
            raise PresenceUnavailableError(
                f"camera:{camera_id}", "no camera is configured with this id"
            )
        with self._locks[camera_id]:
            return self._encode(camera_id, self._read(config))

    def close(self) -> None:
        for source_id, lock in self._locks.items():
            with lock:
                self._discard(source_id)

    def _read(self, config: SourceConfig):
        try:
            return self._device_for(config).read()
        except Exception as exc:
            # A driver can fail in ways that are not ours to enumerate (cv2.error
            # included). Whatever it was, the device is not trusted again until
            # it has been opened from scratch.
            self._discard(config.source_id)
            raise PresenceUnavailableError(f"camera:{config.source_id}", _reason(exc)) from exc

    def _device_for(self, config: SourceConfig) -> CameraDevice:
        device = self._devices.get(config.source_id)
        if device is None:
            device = self._opener(config)
            device.open()
            self._devices[config.source_id] = device
            _log.info("camera source_id=%s opened", config.source_id)
        return device

    def _discard(self, source_id: str) -> None:
        device = self._devices.pop(source_id, None)
        if device is not None:
            device.close()

    def _encode(self, source_id: str, frame) -> bytes:
        try:
            return self._encoder(frame)
        except ValueError as exc:
            raise PresenceUnavailableError(f"camera:{source_id}", str(exc)) from exc
