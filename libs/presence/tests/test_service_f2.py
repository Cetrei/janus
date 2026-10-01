"""F2 wiring in PresenceService: real encrypted snapshots and real clips
(requisito 12, 31). Detection is patched, as in test_service.py, so no ONNX
models are needed."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import KEY_A, FakeFrameSource, make_embedding

from janus_presence.clip_recorder import ClipRecorder
from janus_presence.errors import ClipNotFoundError, PresenceUnavailableError
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore

SOURCE = "front-door"
FRAME_SIDE = 8
DECODED_FRAME_BYTES = FRAME_SIDE * FRAME_SIDE * 3
FPS = 10.0


class FakeFace:
    def __init__(
        self,
        embedding: list[float],
        quality_ok: bool = True,
        bbox: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.embedding = embedding
        self.quality_ok = quality_ok
        self.bbox = bbox


def make_service(
    tmp_path: Path, fake_index, clip_recorder: ClipRecorder | None = None
) -> PresenceService:
    return PresenceService(
        store=PresenceStore(tmp_path / "state", KEY_A),
        index=fake_index,
        model_cache=object(),
        frame_sources={SOURCE: FakeFrameSource({SOURCE: b"frame"})},
        match_threshold=1.0,
        match_threshold_ambiguous=2.0,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
        clip_recorder=clip_recorder,
    )


def _patch_faces(*faces: FakeFace):
    return patch.object(PresenceService, "_embed", return_value=list(faces))


class TestEncryptedSnapshot:
    def test_snapshot_is_stored_encrypted_and_decrypts_to_the_frame(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        frame = b"\xff\xd8 pretend jpeg bytes \xff\xd9"

        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.process_frame(SOURCE, frame)

        person = service._store.get_person(sighting.person_id)
        assert person.snapshot_ref is not None
        on_disk = Path(person.snapshot_ref).read_bytes()
        assert frame not in on_disk
        assert service._store.load_snapshot(sighting.person_id) == frame

    def test_low_quality_face_keeps_no_snapshot(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with _patch_faces(FakeFace(make_embedding(0.0), quality_ok=False)):
            sighting = service.process_frame(SOURCE, b"frame")

        assert service._store.load_snapshot(sighting.person_id) is None

    def test_naming_removes_the_snapshot_file(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.process_frame(SOURCE, b"frame")

        service.name_person(sighting.person_id, "Joanfer")

        assert service._store.load_snapshot(sighting.person_id) is None

    def test_snapshot_write_failure_never_fails_the_sighting(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with (
            patch.object(service._store, "save_snapshot", side_effect=OSError("disk full")),
            _patch_faces(FakeFace(make_embedding(0.0))),
        ):
            sighting = service.process_frame(SOURCE, b"frame")

        assert sighting is not None
        assert service._store.get_person(sighting.person_id).snapshot_ref is None


def _jpeg_frame() -> bytes:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    ok, encoded = cv2.imencode(".jpg", np.zeros((FRAME_SIDE, FRAME_SIDE, 3), dtype=np.uint8))
    assert ok
    return bytes(encoded)


def _read_tracks(clip_ref: str) -> list[dict]:
    tracks_path = Path(clip_ref).with_suffix(".tracks.jsonl")
    lines = tracks_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.mark.skipif(sys.platform == "win32", reason="fake ffmpeg is a POSIX shell script")
class TestClipTracks:
    def test_each_detection_is_written_to_the_sidecar_with_its_person_and_bbox(
        self, tmp_path, fake_index, fake_ffmpeg
    ):
        jpeg = _jpeg_frame()
        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)
        bbox = (1, 2, 3, 4)

        with _patch_faces(FakeFace(make_embedding(0.0), bbox=bbox)):
            first = service.process_frame(SOURCE, jpeg)
            service.process_frame(SOURCE, jpeg)
        service.close()

        tracks = _read_tracks(first.clip_ref)
        assert [track["bbox"] for track in tracks] == [[1, 2, 3, 4], [1, 2, 3, 4]]
        assert {track["person_id"] for track in tracks} == {first.person_id}
        assert [track["t"] for track in tracks] == [0.0, 0.1]

    def test_the_first_track_lands_in_the_clip_that_the_same_sighting_started(
        self, tmp_path, fake_index, fake_ffmpeg
    ):
        jpeg = _jpeg_frame()
        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)

        with _patch_faces(FakeFace(make_embedding(0.0), bbox=(5, 6, 7, 8))):
            first = service.process_frame(SOURCE, jpeg)
        service.close()

        assert first.clip_ref is not None
        assert len(_read_tracks(first.clip_ref)) == 1

    def test_a_face_without_bbox_writes_no_track(self, tmp_path, fake_index, fake_ffmpeg):
        jpeg = _jpeg_frame()
        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)

        with _patch_faces(FakeFace(make_embedding(0.0), bbox=None)):
            first = service.process_frame(SOURCE, jpeg)
        service.close()

        assert _read_tracks(first.clip_ref) == []

    def test_two_faces_in_one_frame_write_two_tracks(self, tmp_path, fake_index, fake_ffmpeg):
        jpeg = _jpeg_frame()
        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)
        faces = (
            FakeFace(make_embedding(0.0), bbox=(1, 1, 2, 2)),
            FakeFace(make_embedding(5.0), bbox=(4, 4, 2, 2)),
        )

        with _patch_faces(*faces):
            service.process_frame(SOURCE, jpeg)
        service.close()

        clip_dir = tmp_path / "clips" / SOURCE
        [sidecar] = clip_dir.glob("*.tracks.jsonl")
        lines = sidecar.read_text(encoding="utf-8").splitlines()
        assert sorted(json.loads(line)["bbox"] for line in lines) == [[1, 1, 2, 2], [4, 4, 2, 2]]

    def test_track_without_an_active_clip_is_ignored(self, tmp_path, fake_index, fake_ffmpeg):
        jpeg = _jpeg_frame()
        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)

        with _patch_faces(FakeFace(make_embedding(0.0), bbox=(1, 2, 3, 4))):
            first = service.process_frame(SOURCE, jpeg)
        recorder.close_all()
        with _patch_faces(FakeFace(make_embedding(0.0), bbox=(1, 2, 3, 4))):
            second = service.process_frame(SOURCE, jpeg)
        service.close()

        assert second.clip_ref is None
        assert len(_read_tracks(first.clip_ref)) == 1

    def test_without_a_recorder_a_bbox_is_harmless(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with _patch_faces(FakeFace(make_embedding(0.0), bbox=(1, 2, 3, 4))):
            sighting = service.process_frame(SOURCE, b"frame")

        assert sighting is not None


class TestRenderClip:
    @pytest.mark.skipif(sys.platform == "win32", reason="fake ffmpeg is a POSIX shell script")
    def test_render_lands_in_the_renders_tree_next_to_the_clips_tree(
        self, tmp_path, fake_index, fake_ffmpeg
    ):
        from test_render import CLIP_NAME, write_tracks, write_video

        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)
        clip = tmp_path / "clips" / SOURCE / CLIP_NAME
        write_video(clip)
        write_tracks(clip)

        rendered = service.render_clip(str(clip))
        service.close()

        assert Path(rendered) == tmp_path / "renders" / SOURCE / CLIP_NAME
        assert Path(rendered).stat().st_size > 0
        assert clip.exists()  # the raw clip is left alone

    def test_rendering_a_missing_clip_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with pytest.raises(ClipNotFoundError):
            service.render_clip(str(tmp_path / "clips" / SOURCE / "nope.mp4"))


class TestRealClips:
    def test_recorder_without_opencv_is_refused_at_construction(self, tmp_path, fake_index):
        recorder = ClipRecorder(tmp_path / "clips")

        with patch.dict(sys.modules, {"cv2": None}):
            with pytest.raises(PresenceUnavailableError):
                make_service(tmp_path, fake_index, clip_recorder=recorder)

    @pytest.mark.skipif(sys.platform == "win32", reason="fake ffmpeg is a POSIX shell script")
    def test_first_sighting_records_a_clip_with_preroll_and_live_frames(
        self, tmp_path, fake_index, fake_ffmpeg
    ):
        cv2 = pytest.importorskip("cv2")
        np = pytest.importorskip("numpy")
        ok, encoded = cv2.imencode(".jpg", np.zeros((FRAME_SIDE, FRAME_SIDE, 3), dtype=np.uint8))
        assert ok
        jpeg = bytes(encoded)

        recorder = ClipRecorder(tmp_path / "clips", fps=FPS, ffmpeg_binary=fake_ffmpeg)
        service = make_service(tmp_path, fake_index, clip_recorder=recorder)

        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.process_frame(SOURCE, jpeg)
            second = service.process_frame(SOURCE, jpeg)
        service.close()

        assert first.clip_ref is not None
        assert second.clip_ref is None
        # One frame seeded from the pre-roll buffer, one live frame.
        assert Path(first.clip_ref).stat().st_size == 2 * DECODED_FRAME_BYTES

    def test_without_a_recorder_record_clip_keeps_its_intent_only_behaviour(
        self, tmp_path, fake_index
    ):
        service = make_service(tmp_path, fake_index)

        clip = service.record_clip(SOURCE, duration_s=5)

        assert clip.clip_ref.endswith(".mp4")
        assert not Path(clip.clip_ref).exists()
        assert service.close_due_clips() == []
