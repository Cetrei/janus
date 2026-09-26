from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from janus_presence.errors import PresenceUnavailableError


class FrameSource(ABC):
    @abstractmethod
    def capture_frame(self, camera_id: str) -> bytes: ...


class LocalCameraSource(FrameSource):
    def __init__(self) -> None:
        self._captures: dict[str, object] = {}

    def capture_frame(self, camera_id: str) -> bytes:
        capture = self._get_or_open_capture(camera_id)
        ok, frame = capture.read()
        if not ok:
            raise PresenceUnavailableError(f"camera '{camera_id}' returned no frame")
        success, encoded = self._encode(frame)
        if not success:
            raise PresenceUnavailableError(f"failed to encode frame from '{camera_id}'")
        return encoded.tobytes()

    def _get_or_open_capture(self, camera_id: str):
        if camera_id in self._captures:
            return self._captures[camera_id]
        try:
            import cv2
        except ImportError as exc:
            raise PresenceUnavailableError("opencv-python is not installed") from exc
        capture = cv2.VideoCapture(self._device_index(camera_id))
        if not capture.isOpened():
            raise PresenceUnavailableError(f"camera '{camera_id}' is busy or absent")
        self._captures[camera_id] = capture
        return capture

    def _encode(self, frame):
        import cv2

        return cv2.imencode(".jpg", frame)

    def _device_index(self, camera_id: str) -> int:
        try:
            return int(camera_id)
        except ValueError:
            return 0

    def release(self, camera_id: str) -> None:
        capture = self._captures.pop(camera_id, None)
        if capture is not None:
            capture.release()


class McpCameraSource(FrameSource):
    def __init__(self, fetch_frame: Callable[[str], bytes]) -> None:
        self._fetch_frame = fetch_frame

    def capture_frame(self, camera_id: str) -> bytes:
        try:
            return self._fetch_frame(camera_id)
        except Exception as exc:
            raise PresenceUnavailableError(
                f"mcp camera '{camera_id}' unavailable: {exc}"
            ) from exc
