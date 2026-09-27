from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from janus_presence.errors import PresenceUnavailableError

__all__ = ["FrameSource", "LocalCameraSource", "McpCameraSource"]


class FrameSource(Protocol):
    """Abstract source of camera frames (requisito 9). presence never
    imports libs/iot or libs/adapters itself: whoever constructs a
    PresenceService decides which FrameSource implementation to inject
    (inversion of dependency, requisito 10)."""

    def capture_frame(self, camera_id: str) -> bytes: ...


class LocalCameraSource(ABC):
    """Direct OpenCV capture, analogous to biometrics' CameraSource. This is
    the default, self-sufficient implementation: no MCP, no Janus core,
    just a local camera device (requisito 9).

    This is an ABC rather than a concrete class because "how a camera_id
    maps to a local device index/path" is host-specific; concrete
    subclasses (or a factory) supply that mapping. This keeps the class
    testable without a real camera by subclassing with a fake mapping.
    """

    @abstractmethod
    def _device_for(self, camera_id: str) -> int | str:
        """Maps a configured camera_id to an OpenCV-openable device
        (an index for a local webcam, or a path/URL for other backends)."""

    def capture_frame(self, camera_id: str) -> bytes:
        import cv2

        device = self._device_for(camera_id)
        capture = cv2.VideoCapture(device)
        try:
            if not capture.isOpened():
                raise PresenceUnavailableError(
                    f"camera:{camera_id}", f"could not open device '{device}'"
                )
            ok, frame = capture.read()
            if not ok or frame is None:
                raise PresenceUnavailableError(
                    f"camera:{camera_id}", "read() returned no frame (camera busy or disconnected)"
                )
            success, encoded = cv2.imencode(".jpg", frame)
            if not success:
                raise PresenceUnavailableError(
                    f"camera:{camera_id}", "could not encode frame as JPEG"
                )
            return bytes(encoded)
        finally:
            capture.release()


class McpCameraSource:
    """Optional adapter for a camera exposed via MCP as `category_id =
    camera` (spec-20, IoT), using the same `tool_map` pattern. Only
    activated when the caller configures `presence.cameras.<id>.source =
    mcp` and injects a reference to the corresponding MCP spoke
    (requisito 9). janus_presence itself never imports libs/iot: the
    `tool_map` callable is supplied entirely by the caller, keeping the
    inversion of dependency from requisito 10 intact.
    """

    def __init__(self, tool_map: dict[str, _McpCameraTool]) -> None:
        self._tool_map = tool_map

    def capture_frame(self, camera_id: str) -> bytes:
        tool = self._tool_map.get(camera_id)
        if tool is None:
            raise PresenceUnavailableError(
                f"camera:{camera_id}", "no MCP camera tool registered for this id"
            )
        frame = tool.capture()
        if not frame:
            raise PresenceUnavailableError(
                f"camera:{camera_id}", "MCP camera tool returned no frame"
            )
        return frame


class _McpCameraTool(Protocol):
    """Minimal shape McpCameraSource expects from an injected MCP camera
    tool. Not an actual MCP client: the caller adapts whatever spec-20
    tool_map entry exists to this shape."""

    def capture(self) -> bytes: ...
