"""SensorSource ABC and its two v1 implementations (requisitos 20-22).

`BiometricService.capture_and_verify` (service.py) is the only intended
caller: sensor capture is a read-only operation on the user's own
hardware, triggered by the core when a channel's policy needs it, never
by an agent on its own (requisito 22). There is no continuous recording:
each call captures one bounded sample for one verification event, then
the sensor is done -- CameraSource/MicrophoneSource hold no background
thread or loop.

CameraSource wraps camera.py (this library's standalone, GUI-extra-only
camera module) rather than duplicating its V4L2/DirectShow backend
selection: camera.py stays importable on its own (opencv-python-headless
production installs never touch it; only the `face-gui` extra's
opencv-python does), and this module is the thin adapter that lets
BiometricService talk to it through the generic SensorSource contract
without service.py needing to know camera.py exists.

MicrophoneSource requires the `sensors` extra (sounddevice, which needs
PortAudio -- bundled on Windows, a system package on Linux/macOS). Unlike
CameraSource, whose face-gui extra is orthogonal to production's `face`
extra (headless vs GUI opencv, mutually exclusive per pyproject.toml's own
comment), `sensors` has no such conflict: sounddevice does not touch cv2
at all, so it can be installed alongside either `face` or `face-gui`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from janus_biometrics.errors import SensorUnavailable

if TYPE_CHECKING:
    from janus_biometrics.base import PcmAudio


@dataclass(frozen=True)
class SensorConfig:
    """One entry from biometrics.sensors (spec-18's Data Models section).
    `device` is sensor-kind-specific: a camera index/path for "camera", a
    device index or name for "microphone"."""

    id: str
    kind: str  # "camera" | "microphone"
    device: str | int


class SensorSource(ABC):
    """Read-only capture from one piece of local hardware. `id` identifies
    the configured sensor (SensorConfig.id), not the underlying hardware
    index, so BiometricService/config can refer to it stably even if the
    hardware enumeration order changes between runs.

    Only the capture method matching a sensor's own kind is meaningful;
    calling the other raises NotImplementedError rather than silently
    returning nothing, so a misconfigured channel (camera sensor wired to
    a voice check, or vice versa) fails loudly instead of producing an
    empty capture that looks like a real but-empty sample.
    """

    id: str

    @abstractmethod
    def capture_frame(self) -> bytes:
        """Captures one still frame from a camera sensor, encoded (PNG) so
        the result can go straight into BiometricService.verify_face's
        `image: bytes` parameter. Raises SensorUnavailable if the device
        cannot be opened or a frame cannot be read."""
        ...

    @abstractmethod
    def capture_audio(self, max_s: float) -> PcmAudio:
        """Captures up to `max_s` seconds of audio from a microphone
        sensor as PcmAudio (16-bit mono, 16 kHz -- base.PcmAudio's own
        contract), ready for BiometricService.verify_voice. Raises
        SensorUnavailable if the device cannot be opened or captured
        from."""
        ...

    def close(self) -> None:
        """Releases any held hardware handle. Default no-op: a
        SensorSource that opens-and-closes per capture (both v1
        implementations do) has nothing to release between calls; this
        exists so BiometricService can call close() uniformly on
        shutdown without checking which kind of sensor it has."""
        return None


class CameraSource(SensorSource):
    """Camera-backed SensorSource. Opens camera.py's Camera for the
    duration of one capture and releases it immediately after (requisito
    22: a bounded capture per event, not a held-open device), rather than
    keeping the device open between verifications -- this also means a
    CameraSource does not compete with another application for the device
    except for the brief window of an actual capture.
    """

    def __init__(self, config: SensorConfig) -> None:
        if config.kind != "camera":
            raise ValueError(f"CameraSource requires kind='camera', got '{config.kind}'")
        self.id = config.id
        self._device = config.device

    def capture_frame(self) -> bytes:
        # Local import: camera.py needs the `face-gui` extra (opencv with
        # GUI support), which production/headless installs never have and
        # must not require just to import janus_biometrics.sensors --
        # only actually calling capture_frame() on a CameraSource needs it.
        from janus_biometrics import camera as camera_module

        index = int(self._device)
        cam = camera_module.Camera(index=index)
        try:
            cam.open()
            frame = cam.read()
        except camera_module.CameraError:
            # CameraUnavailable/CameraReadError already inherit
            # SensorUnavailable (see camera.py's module docstring for why
            # this dual inheritance exists rather than raising a fresh
            # SensorUnavailable here and losing the original detail).
            raise
        finally:
            cam.close()

        import cv2  # same face-gui extra as camera_module, already imported above

        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise SensorUnavailable(self.id, "failed to encode captured frame")
        return encoded.tobytes()

    def capture_audio(self, max_s: float) -> PcmAudio:
        raise NotImplementedError("CameraSource does not support audio capture")


class MicrophoneSource(SensorSource):
    """Microphone-backed SensorSource (extra `[sensors]`, sounddevice).
    Captures a single bounded recording per call, normalized to the
    16-bit mono 16 kHz PcmAudio contract verify_voice expects (requisito
    9's normalization is the provider's job on the samples themselves;
    this class's job is only to deliver audio already at the right
    sample rate/format so that normalization has nothing to fix).
    """

    _SAMPLE_RATE = 16_000

    def __init__(self, config: SensorConfig) -> None:
        if config.kind != "microphone":
            raise ValueError(f"MicrophoneSource requires kind='microphone', got '{config.kind}'")
        self.id = config.id
        self._device = config.device

    def capture_frame(self) -> bytes:
        raise NotImplementedError("MicrophoneSource does not support frame capture")

    def capture_audio(self, max_s: float) -> PcmAudio:
        # Local import: sounddevice/PortAudio is the optional `sensors`
        # extra, not a hard dependency of janus_biometrics -- importing
        # this module (or even constructing a MicrophoneSource) must not
        # require it; only an actual capture_audio() call does.
        import numpy as np
        import sounddevice as sd

        from janus_biometrics.base import PcmAudio

        try:
            frame_count = int(max_s * self._SAMPLE_RATE)
            recording = sd.rec(
                frame_count,
                samplerate=self._SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=self._device,
            )
            sd.wait()
        except sd.PortAudioError as exc:
            raise SensorUnavailable(self.id, str(exc)) from exc

        samples: np.ndarray = recording.reshape(-1)
        return PcmAudio(samples=samples.tobytes(), sample_rate=self._SAMPLE_RATE)
