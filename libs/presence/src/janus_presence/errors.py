class PresenceError(Exception):
    """Base error for janus_presence."""


class PresenceUnavailableError(PresenceError):
    """Raised when a required backing resource (the HNSW index, a camera)
    is not available. Never a silent crash or a fabricated result: any
    caller of PresenceService must be prepared to catch this (spec
    Non-Functional Requirements, Reliability)."""

    def __init__(self, resource: str, reason: str) -> None:
        super().__init__(f"Presence resource '{resource}' is unavailable: {reason}")
        self.resource = resource
        self.reason = reason


class PersonNotFoundError(PresenceError):
    def __init__(self, person_id: str) -> None:
        super().__init__(f"No PersonRecord found for person_id '{person_id}'")
        self.person_id = person_id


class ClipNotFoundError(PresenceError):
    def __init__(self, clip_ref: str) -> None:
        super().__init__(f"No clip file found at '{clip_ref}'")
        self.clip_ref = clip_ref


class CameraNotFoundError(PresenceError):
    def __init__(self, camera_id: str) -> None:
        super().__init__(f"No camera configured with camera_id '{camera_id}'")
        self.camera_id = camera_id
