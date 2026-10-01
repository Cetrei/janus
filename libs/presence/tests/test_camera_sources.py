"""Persistent camera sources (requisito 21): a device stays open between
captures, and any failure forces it to be opened again from scratch."""

from __future__ import annotations

import pytest

from janus_presence.camera_sources import (
    PersistentCameraSource,
    UrlCamera,
    enabled_cameras,
    open_camera_device,
)
from janus_presence.errors import PresenceUnavailableError
from janus_presence.models import SourceConfig, SourceKind, SourceLocation

SOURCE = "cuarto"


def make_config(
    source_id: str = SOURCE,
    kind: SourceKind = SourceKind.CAMERA,
    source: SourceLocation = SourceLocation.LOCAL,
    device: str = "0",
    enabled: bool = True,
) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        kind=kind,
        source=source,
        device=device,
        label=source_id,
        enabled=enabled,
    )


class FakeDevice:
    """Plays back a script: bytes are frames, exceptions are raised."""

    def __init__(self, *reads: object) -> None:
        self.reads = list(reads)
        self.open_error: Exception | None = None
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1
        if self.open_error is not None:
            raise self.open_error

    def read(self):
        item = self.reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed += 1


class FakeOpener:
    """Hands out one scripted device per open request."""

    def __init__(self, *devices: FakeDevice) -> None:
        self.devices = list(devices)
        self.requests: list[str] = []

    def __call__(self, config: SourceConfig) -> FakeDevice:
        self.requests.append(config.source_id)
        return self.devices.pop(0)


def passthrough(frame: object) -> bytes:
    return frame  # type: ignore[return-value]


def make_source(opener: FakeOpener, encoder=passthrough) -> PersistentCameraSource:
    return PersistentCameraSource([make_config()], opener=opener, encoder=encoder)


class TestPersistentCameraSource:
    def test_the_device_is_opened_once_and_kept_open(self):
        device = FakeDevice(b"a", b"b", b"c")
        opener = FakeOpener(device)
        source = make_source(opener)

        frames = [source.capture_frame(SOURCE) for _ in range(3)]

        assert frames == [b"a", b"b", b"c"]
        assert opener.requests == [SOURCE]
        assert device.opened == 1
        assert device.closed == 0

    def test_a_failed_read_closes_the_device_and_the_next_capture_reopens_it(self):
        broken = FakeDevice(b"a", PresenceUnavailableError("camera:stream", "no frame"))
        fresh = FakeDevice(b"b")
        opener = FakeOpener(broken, fresh)
        source = make_source(opener)

        assert source.capture_frame(SOURCE) == b"a"
        with pytest.raises(PresenceUnavailableError) as failure:
            source.capture_frame(SOURCE)
        recovered = source.capture_frame(SOURCE)

        assert failure.value.resource == f"camera:{SOURCE}"
        assert broken.closed == 1
        assert recovered == b"b"
        assert opener.requests == [SOURCE, SOURCE]

    def test_a_driver_exception_is_reported_as_unavailable_and_forces_a_reopen(self):
        device = FakeDevice(RuntimeError("cv2 exploded"))
        source = make_source(FakeOpener(device))

        with pytest.raises(PresenceUnavailableError) as failure:
            source.capture_frame(SOURCE)

        assert "cv2 exploded" in failure.value.reason
        assert device.closed == 1

    def test_a_device_that_fails_to_open_is_tried_again_on_the_next_capture(self):
        stuck = FakeDevice()
        stuck.open_error = PresenceUnavailableError("camera:stream", "busy")
        opener = FakeOpener(stuck, FakeDevice(b"a"))
        source = make_source(opener)

        with pytest.raises(PresenceUnavailableError, match=f"camera:{SOURCE}"):
            source.capture_frame(SOURCE)

        assert source.capture_frame(SOURCE) == b"a"
        assert opener.requests == [SOURCE, SOURCE]

    def test_a_frame_that_cannot_be_encoded_keeps_the_device_open(self):
        def refuse(frame: object) -> bytes:
            raise ValueError("could not encode the frame as JPEG")

        device = FakeDevice(b"a")
        source = make_source(FakeOpener(device), encoder=refuse)

        with pytest.raises(PresenceUnavailableError, match="JPEG"):
            source.capture_frame(SOURCE)

        assert device.closed == 0

    def test_an_unknown_camera_is_unavailable(self):
        source = make_source(FakeOpener())

        with pytest.raises(PresenceUnavailableError, match="otra"):
            source.capture_frame("otra")

    def test_close_releases_every_open_device_and_is_idempotent(self):
        device = FakeDevice(b"a")
        source = make_source(FakeOpener(device))
        source.capture_frame(SOURCE)

        source.close()
        source.close()

        assert device.closed == 1


class TestSourceSelection:
    def test_only_enabled_cameras_are_selected(self):
        configs = [
            make_config("cuarto"),
            make_config("garaje", enabled=False),
            make_config("mic", kind=SourceKind.MICROPHONE, device="default"),
        ]

        assert [config.source_id for config in enabled_cameras(configs)] == ["cuarto"]

    def test_a_stream_source_gets_a_url_camera(self):
        config = make_config(source=SourceLocation.RTSP, device="rtsp://cam.local/stream")

        assert isinstance(open_camera_device(config), UrlCamera)
