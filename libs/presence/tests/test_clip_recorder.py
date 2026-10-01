from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from janus_presence import clip_recorder as clip_recorder_module
from janus_presence.clip_recorder import ClipRecorder

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the fake ffmpeg fixture is a POSIX shell script"
)

SOURCE = "front-door"
FRAME_WIDTH = 4
FRAME_HEIGHT = 2
FPS = 10.0
LONG_CLIP_S = 60


class FakeFrame:
    """Minimal stand-in for a BGR ndarray: ClipRecorder only reads `.shape`
    and calls `.tobytes()`, so tests need no numpy or OpenCV."""

    def __init__(self, fill: int, width: int = FRAME_WIDTH, height: int = FRAME_HEIGHT) -> None:
        self.shape = (height, width, 3)
        self._payload = bytes([fill]) * (width * height * 3)

    def tobytes(self) -> bytes:
        return self._payload


def make_recorder(tmp_path: Path, ffmpeg_binary: str, **kwargs) -> ClipRecorder:
    return ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=ffmpeg_binary, **kwargs)


def clip_files(tmp_path: Path, suffix: str) -> list[Path]:
    return sorted((tmp_path / "clips").rglob(f"*{suffix}"))


class TestRecording:
    def test_frames_after_start_are_written_to_the_clip_file(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)

        frames = [FakeFrame(1), FakeFrame(2)]
        for frame in frames:
            recorder.ingest_frame(SOURCE, frame)
        closed = recorder.close(SOURCE)

        assert closed == clip_ref
        assert Path(clip_ref).read_bytes() == b"".join(f.tobytes() for f in frames)

    def test_preroll_frames_come_first_in_order(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        earlier = [FakeFrame(1), FakeFrame(2), FakeFrame(3)]
        for frame in earlier:
            recorder.ingest_frame(SOURCE, frame)

        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)
        live = FakeFrame(4)
        recorder.ingest_frame(SOURCE, live)
        recorder.close(SOURCE)

        expected = b"".join(f.tobytes() for f in [*earlier, live])
        assert Path(clip_ref).read_bytes() == expected

    def test_preroll_window_drops_frames_older_than_preroll_s(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg, preroll_s=0)
        recorder.ingest_frame(SOURCE, FakeFrame(1))

        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)
        closed = recorder.close(SOURCE)

        assert closed is None
        assert not Path(clip_ref).exists()

    def test_frame_of_a_different_size_is_skipped(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)

        first = FakeFrame(1)
        recorder.ingest_frame(SOURCE, first)
        recorder.ingest_frame(SOURCE, FakeFrame(2, width=6))
        recorder.close(SOURCE)

        assert Path(clip_ref).read_bytes() == first.tobytes()

    def test_frames_after_the_end_time_are_ignored(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        clip_ref = recorder.start(SOURCE, duration_s=0)

        recorder.ingest_frame(SOURCE, FakeFrame(1))
        closed = recorder.close(SOURCE)

        assert closed is None
        assert not Path(clip_ref).exists()

    def test_closed_clip_file_is_private(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)
        recorder.ingest_frame(SOURCE, FakeFrame(1))
        recorder.close(SOURCE)

        assert Path(clip_ref).stat().st_mode & 0o077 == 0


class TestOneClipPerSource:
    def test_second_start_returns_the_same_clip(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        first = recorder.start(SOURCE, LONG_CLIP_S)
        second = recorder.start(SOURCE, LONG_CLIP_S)

        assert second == first
        assert recorder.is_recording(SOURCE)
        recorder.close_all()

    def test_new_trigger_extends_the_end_time(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.start(SOURCE, duration_s=0)
        assert recorder.due_sources() == [SOURCE]

        recorder.start(SOURCE, LONG_CLIP_S)

        assert recorder.due_sources() == []
        recorder.close_all()

    def test_extend_never_shortens_the_clip(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.start(SOURCE, LONG_CLIP_S)

        recorder.extend(SOURCE, duration_s=0)

        assert recorder.due_sources() == []
        recorder.close_all()

    def test_extend_without_an_active_clip_is_a_noop(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.extend(SOURCE, LONG_CLIP_S)

        assert not recorder.is_recording(SOURCE)

    def test_two_clips_in_the_same_second_get_different_files(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        first = recorder.start(SOURCE, LONG_CLIP_S)
        recorder.ingest_frame(SOURCE, FakeFrame(1))
        recorder.close(SOURCE)

        second = recorder.start(SOURCE, LONG_CLIP_S)
        recorder.ingest_frame(SOURCE, FakeFrame(2))
        recorder.close(SOURCE)

        assert second != first
        assert Path(first).exists()
        assert Path(second).exists()

    def test_close_due_closes_only_finished_clips(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.start("garden", duration_s=0)
        recorder.start(SOURCE, LONG_CLIP_S)
        recorder.ingest_frame(SOURCE, FakeFrame(1))

        recorder.close_due()

        assert not recorder.is_recording("garden")
        assert recorder.is_recording(SOURCE)
        recorder.close_all()


class TestTracksSidecar:
    def test_track_time_is_the_frame_index_over_fps(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)
        for fill in (1, 2, 3):
            recorder.ingest_frame(SOURCE, FakeFrame(fill))

        recorder.record_track(SOURCE, (10, 20, 30, 40), "person-1")
        recorder.close(SOURCE)

        tracks_path = Path(clip_ref).with_suffix(".tracks.jsonl")
        lines = tracks_path.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == [
            {"t": 0.2, "bbox": [10, 20, 30, 40], "person_id": "person-1"}
        ]

    def test_track_before_any_frame_is_at_time_zero(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        clip_ref = recorder.start(SOURCE, LONG_CLIP_S)
        recorder.record_track(SOURCE, (1, 2, 3, 4), None)
        recorder.ingest_frame(SOURCE, FakeFrame(1))
        recorder.close(SOURCE)

        tracks_path = Path(clip_ref).with_suffix(".tracks.jsonl")
        record = json.loads(tracks_path.read_text(encoding="utf-8").splitlines()[0])
        assert record == {"t": 0.0, "bbox": [1, 2, 3, 4], "person_id": None}

    def test_track_without_an_active_clip_writes_nothing(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.record_track(SOURCE, (1, 2, 3, 4), "person-1")

        assert clip_files(tmp_path, ".tracks.jsonl") == []


class TestDegradedRecording:
    def test_close_with_no_frames_leaves_no_files(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.start(SOURCE, LONG_CLIP_S)

        assert recorder.close(SOURCE) is None
        assert clip_files(tmp_path, ".mp4") == []
        assert clip_files(tmp_path, ".tracks.jsonl") == []

    def test_close_without_a_clip_returns_none(self, tmp_path, fake_ffmpeg):
        recorder = make_recorder(tmp_path, fake_ffmpeg)

        assert recorder.close(SOURCE) is None

    def test_missing_ffmpeg_never_raises_into_the_caller(self, tmp_path):
        recorder = make_recorder(tmp_path, "janus-test-no-such-ffmpeg-binary")
        recorder.start(SOURCE, LONG_CLIP_S)

        recorder.ingest_frame(SOURCE, FakeFrame(1))
        recorder.ingest_frame(SOURCE, FakeFrame(2))
        closed = recorder.close(SOURCE)

        assert closed is None
        assert clip_files(tmp_path, ".mp4") == []

    def test_a_burst_of_frames_neither_blocks_nor_fails(self, tmp_path, fake_ffmpeg):
        # Enqueueing is non blocking: whether the writer keeps up or the queue
        # fills and drops, ingest_frame returns and the clip still closes.
        recorder = make_recorder(tmp_path, fake_ffmpeg)
        recorder.start(SOURCE, LONG_CLIP_S)

        for fill in range(200):
            recorder.ingest_frame(SOURCE, FakeFrame(fill % 250))

        assert recorder.close(SOURCE) is not None


class FakeClock:
    """Replaces the recorder's `monotonic` so the ceiling can be tested
    without waiting for it."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clip_recorder_module, "monotonic", fake)
    return fake


class TestClipMaxDuration:
    def test_a_first_request_longer_than_the_cap_is_cut_to_the_cap(
        self, tmp_path, fake_ffmpeg, clock
    ):
        recorder = make_recorder(tmp_path, fake_ffmpeg, clip_max_s=5)
        recorder.start(SOURCE, duration_s=3600)

        clock.now = 104.9
        assert recorder.due_sources() == []
        clock.now = 105.0
        assert recorder.due_sources() == [SOURCE]
        recorder.close_all()

    def test_repeated_triggers_never_push_the_end_past_the_cap(
        self, tmp_path, fake_ffmpeg, clock
    ):
        recorder = make_recorder(tmp_path, fake_ffmpeg, clip_max_s=5)
        recorder.start(SOURCE, duration_s=3)
        for now in (102.0, 104.0, 104.5):
            clock.now = now
            recorder.start(SOURCE, duration_s=3)

        clock.now = 105.0
        assert recorder.due_sources() == [SOURCE]
        recorder.close_all()

    def test_extend_never_pushes_the_end_past_the_cap(self, tmp_path, fake_ffmpeg, clock):
        recorder = make_recorder(tmp_path, fake_ffmpeg, clip_max_s=5)
        recorder.start(SOURCE, duration_s=3)
        clock.now = 104.0

        recorder.extend(SOURCE, duration_s=3600)

        clock.now = 105.0
        assert recorder.due_sources() == [SOURCE]
        recorder.close_all()

    def test_triggers_inside_the_cap_still_extend_the_clip(self, tmp_path, fake_ffmpeg, clock):
        recorder = make_recorder(tmp_path, fake_ffmpeg, clip_max_s=30)
        recorder.start(SOURCE, duration_s=3)
        clock.now = 102.0
        recorder.start(SOURCE, duration_s=3)  # end moves from 103 to 105

        clock.now = 104.0
        assert recorder.due_sources() == []
        clock.now = 105.0
        assert recorder.due_sources() == [SOURCE]
        recorder.close_all()


class TestConfiguration:
    def test_non_positive_clip_max_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            ClipRecorder(tmp_path / "clips", clip_max_s=0)

    def test_negative_preroll_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            ClipRecorder(tmp_path / "clips", preroll_s=-1)

    def test_non_positive_fps_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            ClipRecorder(tmp_path / "clips", fps=0)
