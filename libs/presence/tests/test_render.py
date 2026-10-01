from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

from janus_presence.errors import ClipNotFoundError, PresenceUnavailableError
from janus_presence.render import (
    Identity,
    RenderStyle,
    TrackPoint,
    clip_started_at,
    ease_box,
    focus_at,
    load_tracks,
    render_clip,
    render_path_for,
    step_toward,
    tracks_path_for,
)

CLIP_NAME = "20260929T012833.mp4"
FRAME_WIDTH = 64
FRAME_HEIGHT = 48
FPS = 10.0
FRAME_COUNT = 20
HOLD_S = 1.0


def point(t: float, bbox=(10, 10, 20, 20), person_id: str | None = "p1") -> TrackPoint:
    return TrackPoint(t=t, bbox=bbox, person_id=person_id)


class TestFocusAt:
    def test_no_tracks_means_no_focus(self):
        assert focus_at([], 1.0, HOLD_S) is None

    def test_a_track_in_the_future_is_not_a_focus_yet(self):
        assert focus_at([point(2.0)], 1.0, HOLD_S) is None

    def test_the_last_face_stays_in_focus_for_the_hold_time(self):
        tracks = [point(1.0)]

        assert focus_at(tracks, 1.9, HOLD_S) == tracks[0]
        assert focus_at(tracks, 2.1, HOLD_S) is None

    def test_the_most_recent_track_wins(self):
        older, newer = point(1.0, bbox=(1, 1, 5, 5)), point(1.5, bbox=(2, 2, 5, 5))

        assert focus_at([older, newer], 1.6, HOLD_S) == newer

    def test_the_biggest_face_wins_at_the_same_instant(self):
        small = point(1.0, bbox=(1, 1, 5, 5), person_id="a")
        big = point(1.0, bbox=(9, 9, 30, 30), person_id="b")

        assert focus_at([small, big], 1.0, HOLD_S) == big

    def test_a_box_with_no_area_is_never_a_focus(self):
        assert focus_at([point(1.0, bbox=(5, 5, 0, 12))], 1.0, HOLD_S) is None


class TestSmoothing:
    def test_ease_box_moves_a_fraction_toward_the_target(self):
        assert ease_box((0.0, 0.0, 10.0, 10.0), (10.0, 20.0, 10.0, 30.0), 0.5) == (
            5.0,
            10.0,
            10.0,
            20.0,
        )

    def test_step_toward_never_overshoots(self):
        assert step_toward(0.0, 0.7, 0.5) == 0.5
        assert step_toward(0.5, 0.7, 0.5) == 0.7
        assert step_toward(0.7, 0.0, 0.5) == pytest.approx(0.2)
        assert step_toward(0.2, 0.0, 0.5) == 0.0


class TestSidecarAndNames:
    def test_load_tracks_reads_them_oldest_first(self, tmp_path):
        path = tmp_path / "a.tracks.jsonl"
        rows = [
            {"t": 0.2, "bbox": [1, 2, 3, 4], "person_id": "p2"},
            {"t": 0.1, "bbox": [5, 6, 7, 8], "person_id": None},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

        tracks = load_tracks(path)

        assert [track.t for track in tracks] == [0.1, 0.2]
        assert tracks[0].person_id is None
        assert tracks[1].bbox == (1, 2, 3, 4)

    def test_a_truncated_last_line_is_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "a.tracks.jsonl"
        good = json.dumps({"t": 0.1, "bbox": [1, 2, 3, 4], "person_id": "p1"})
        path.write_text(good + '\n{"t": 0.2, "bbo', encoding="utf-8")

        assert len(load_tracks(path)) == 1

    def test_a_missing_sidecar_is_an_empty_list(self, tmp_path):
        assert load_tracks(tmp_path / "nope.tracks.jsonl") == []

    def test_clip_start_comes_from_the_file_name(self):
        assert clip_started_at("/x/cam/20260929T012833.mp4") == datetime(2026, 9, 29, 1, 28, 33)

    def test_a_disambiguated_name_still_parses(self):
        assert clip_started_at("/x/cam/20260929T012833_2.mp4") == datetime(2026, 9, 29, 1, 28, 33)

    def test_an_unknown_name_gives_no_start(self):
        assert clip_started_at("/x/cam/manual.mp4") is None

    def test_sidecar_and_render_paths(self, tmp_path):
        clip = tmp_path / "clips" / "front-door" / CLIP_NAME

        assert tracks_path_for(clip) == clip.with_suffix(".tracks.jsonl")
        assert render_path_for(clip, tmp_path / "renders") == (
            tmp_path / "renders" / "front-door" / CLIP_NAME
        )


class TestRenderStyle:
    @pytest.mark.parametrize(
        "kwargs",
        [{"zoom": -0.1}, {"zoom": 1.1}, {"hold_s": -1}, {"zoom_step": 0}, {"zoom_step": 1.5}],
    )
    def test_out_of_range_values_are_rejected(self, kwargs):
        with pytest.raises(ValueError):
            RenderStyle(**kwargs)


# -- through OpenCV and a fake ffmpeg -----------------------------------------------


def write_video(path: Path) -> int:
    """A small real mp4 the renderer can decode. Returns how many frames it
    decodes to, which is what the render must reproduce."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (FRAME_WIDTH, FRAME_HEIGHT)
    )
    if not writer.isOpened():
        pytest.skip("this OpenCV build cannot encode mp4v")
    for index in range(FRAME_COUNT):
        writer.write(np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), index * 10 % 255, dtype=np.uint8))
    writer.release()
    capture = cv2.VideoCapture(str(path))
    decoded = 0
    while capture.read()[0]:
        decoded += 1
    capture.release()
    return decoded


def write_tracks(clip: Path, person_id: str = "p1") -> None:
    row = {"t": 0.5, "bbox": [20, 10, 20, 20], "person_id": person_id}
    tracks_path_for(clip).write_text(json.dumps(row) + "\n", encoding="utf-8")


def resolver_for(calls: list[str]):
    def resolve(person_id: str) -> Identity | None:
        calls.append(person_id)
        return Identity(label="Joanfer", role="owner", known=True)

    return resolve


@pytest.mark.skipif(sys.platform == "win32", reason="the fake ffmpeg fixture is a POSIX script")
class TestRenderClip:
    def test_the_render_has_one_frame_per_decoded_frame(self, tmp_path, fake_ffmpeg):
        clip = tmp_path / "clips" / "cam" / CLIP_NAME
        decoded = write_video(clip)
        write_tracks(clip)
        output = tmp_path / "renders" / "cam" / CLIP_NAME

        result = render_clip(clip, output, resolver_for([]), ffmpeg_binary=fake_ffmpeg)

        assert result == str(output)
        assert output.stat().st_size == decoded * FRAME_WIDTH * FRAME_HEIGHT * 3
        assert not list(output.parent.glob("*.partial.mp4"))

    def test_a_clip_with_a_face_renders_differently_from_one_without(
        self, tmp_path, fake_ffmpeg
    ):
        with_face = tmp_path / "with" / CLIP_NAME
        write_video(with_face)
        write_tracks(with_face)
        without_face = tmp_path / "without" / CLIP_NAME
        without_face.parent.mkdir()
        shutil.copy(with_face, without_face)

        first = render_clip(
            with_face, tmp_path / "out1.mp4", resolver_for([]), ffmpeg_binary=fake_ffmpeg
        )
        second = render_clip(
            without_face, tmp_path / "out2.mp4", resolver_for([]), ffmpeg_binary=fake_ffmpeg
        )

        assert Path(first).stat().st_size == Path(second).stat().st_size
        assert Path(first).read_bytes() != Path(second).read_bytes()

    def test_identity_is_resolved_once_per_person(self, tmp_path, fake_ffmpeg):
        clip = tmp_path / "clips" / "cam" / CLIP_NAME
        write_video(clip)
        write_tracks(clip)
        calls: list[str] = []

        render_clip(clip, tmp_path / "out.mp4", resolver_for(calls), ffmpeg_binary=fake_ffmpeg)

        assert calls == ["p1"]

    def test_a_person_the_store_no_longer_knows_still_renders(self, tmp_path, fake_ffmpeg):
        clip = tmp_path / "clips" / "cam" / CLIP_NAME
        write_video(clip)
        write_tracks(clip)

        result = render_clip(
            clip, tmp_path / "out.mp4", lambda person_id: None, ffmpeg_binary=fake_ffmpeg
        )

        assert Path(result).exists()

    def test_a_missing_clip_raises(self, tmp_path, fake_ffmpeg):
        with pytest.raises(ClipNotFoundError):
            render_clip(
                tmp_path / "nope.mp4",
                tmp_path / "out.mp4",
                resolver_for([]),
                ffmpeg_binary=fake_ffmpeg,
            )

    def test_missing_ffmpeg_leaves_no_output(self, tmp_path):
        clip = tmp_path / "clips" / "cam" / CLIP_NAME
        write_video(clip)
        output = tmp_path / "out" / "render.mp4"

        with pytest.raises(PresenceUnavailableError):
            render_clip(
                clip, output, resolver_for([]), ffmpeg_binary="janus-test-no-such-ffmpeg-binary"
            )

        assert not output.exists()
        assert not list(output.parent.glob("*.partial.mp4"))

    def test_an_ffmpeg_that_fails_leaves_no_output(self, tmp_path):
        clip = tmp_path / "clips" / "cam" / CLIP_NAME
        write_video(clip)
        failing = tmp_path / "failing-ffmpeg"
        failing.write_text("#!/bin/sh\ncat > /dev/null\nexit 1\n")
        failing.chmod(0o755)
        output = tmp_path / "out" / "render.mp4"

        with pytest.raises(PresenceUnavailableError):
            render_clip(clip, output, resolver_for([]), ffmpeg_binary=str(failing))

        assert not output.exists()
        assert not list(output.parent.glob("*.partial.mp4"))

    def test_the_finished_render_is_private(self, tmp_path, fake_ffmpeg):
        clip = tmp_path / "clips" / "cam" / CLIP_NAME
        write_video(clip)
        output = tmp_path / "out.mp4"

        render_clip(clip, output, resolver_for([]), ffmpeg_binary=fake_ffmpeg)

        assert output.stat().st_mode & 0o077 == 0
