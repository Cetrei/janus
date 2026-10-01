"""Real clip recording (SPEC.md ampliacion 2026-09-27, requisito 31).

Before this module, `PresenceService.record_clip` only computed a
`clip_ref` path and logged an intent. This is that phase (F2): an actual
`.mp4` file with real bytes.

Design, matching requisito 31 point by point:

* **Pre-roll buffer.** `ClipRecorder` keeps the last `preroll_s` seconds of
  frames for each source in a small in-memory ring buffer, filled by
  `ingest_frame()` on every frame the detection loop already decoded (so
  this costs no extra camera read). When a clip starts, the buffer seeds
  the file before any new frame arrives, so the clip shows what led up to
  the trigger and not only what came after it.
* **One clip per camera at a time; a new trigger extends it.** `start()` is
  idempotent while a clip is already recording for that `source_id`: it
  pushes the end time further out, the same way `_touch_visit` extends an
  open `Visit` instead of opening a second one.
* **Separate writer thread.** Each active clip owns a bounded queue and one
  writer thread. `ingest_frame()` only enqueues (never blocks); the thread
  owns ffmpeg and its stdin pipe, so a slow disk or a stalled encoder can
  never hold up the detection loop. A full queue drops the frame and logs
  once per clip.
* **ffmpeg does the encoding.** Launched through `janus_platform.spawn` per
  the platform convention (`Popen`, never `asyncio.create_subprocess_exec`).
  Raw BGR frames are piped to its stdin; this module never touches video
  encoding itself. ffmpeg needs the frame size on its command line before
  any bytes arrive, so the process is spawned lazily by the writer thread
  on the first frame it dequeues.
* **`.tracks.jsonl` sidecar.** One JSON object per line, `{"t": <seconds on
  the clip's own timeline>, "bbox": [x, y, w, h], "person_id": "..."}`,
  appended by `record_track()`. `t` is derived from the number of frames
  accepted so far divided by `fps`, which is exactly the timestamp ffmpeg
  assigns to that frame in the file, so the sidecar stays aligned with the
  video whatever the wall clock did. `render_clip` (requisito 32, a later
  step) reads it back to know where to zoom.
* **No audio.** No audio source is ever given to this recorder, and ffmpeg
  runs with `-an`, so there is nothing to mute or discard.

What this module deliberately does not do: decide when to record
(`PresenceService` already implements the deterministic, decision model and
manual triggers of requisitos 14 to 16); identify or track faces across
frames (`record_track` appends whatever bbox and person_id the caller
computed); render an overlay or zoom video (requisito 32).

Length ceiling: `clip_max_s` (default 60) caps a clip counted from the trigger
that started it. `start` and `extend` push the end time out, but never past
that ceiling, so repeated first-sighting triggers cannot grow one file
without bound.

Known limit: the container timeline is `frame_index / fps`. If frames reach
`ingest_frame` at a rate different from `fps`, the clip plays faster or
slower than real time. Configure `fps` to the rate the runner observes at.
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import TextIO

from janus_platform.paths import make_private
from janus_platform.process import ProcessHandle, spawn

from janus_presence.errors import PresenceUnavailableError

_log = logging.getLogger(__name__)

# Frames handed to this module are BGR (OpenCV convention throughout this
# codebase, see camera.py and overlay.py in biometrics), so ffmpeg must be
# told bgr24, not rgb24.
_RAW_PIXEL_FORMAT = "bgr24"
# ffmpeg's encoder name for MPEG-4 part 2. "mp4v" is the FourCC OpenCV uses,
# not a name ffmpeg accepts with -c:v. Codec choice stays open until it is
# measured on real hardware (SPEC.md Open Questions).
_DEFAULT_CODEC = "mpeg4"
_DEFAULT_FPS = 10.0
_DEFAULT_PREROLL_S = 5
# Hard ceiling on one clip's length, counted from the trigger that started
# it. Every first sighting extends the clip, so without a ceiling a person
# who keeps being read as someone new could keep one file growing forever.
_DEFAULT_CLIP_MAX_S = 60.0

_MIN_QUEUE_FRAMES = 64
_QUEUE_PREROLL_FACTOR = 2
_WRITER_POLL_S = 0.1
_FFMPEG_EXIT_TIMEOUT_S = 10.0
_FFMPEG_EXIT_POLL_S = 0.05
_WRITER_JOIN_TIMEOUT_S = 15.0
_KILLED_JOIN_TIMEOUT_S = 2.0
_TRACKS_SUFFIX = ".tracks.jsonl"
# libx264-class encoders reject odd dimensions with yuv420p; padding to even
# is harmless for mpeg4 and keeps the codec swappable.
_EVEN_DIMENSIONS_FILTER = "pad=ceil(iw/2)*2:ceil(ih/2)*2"


@dataclass
class _PrerollFrame:
    captured_at: float  # time.monotonic(), for age comparisons
    frame_bgr: object  # np.ndarray; left untyped so numpy stays an optional import here


@dataclass
class _ActiveClip:
    """State for one in-progress recording on one source.

    Fields in the first group are guarded by `lock`. The second group is
    owned by the writer thread alone and only read by `close()` after that
    thread has been joined.
    """

    source_id: str
    clip_ref: str
    clip_path: Path
    tracks_path: Path
    tracks_handle: TextIO
    frames: queue.Queue
    end_monotonic: float  # extended by _extend(), never rewound
    max_end_monotonic: float  # start + clip_max_s: _extend() never goes past it
    started_recording_at: datetime
    lock: threading.Lock = field(default_factory=threading.Lock)
    frames_accepted: int = 0
    frames_dropped: int = 0
    closed: bool = False
    stop: threading.Event = field(default_factory=threading.Event)
    writer: threading.Thread | None = None

    # Writer thread only.
    process: ProcessHandle | None = None
    frame_size: tuple[int, int] | None = None  # (width, height) ffmpeg was told
    encoded_frames: int = 0
    failed: bool = False


class ClipRecorder:
    """Owns pre-roll buffers and in-progress recordings for every source.

    One instance is shared by a `PresenceService`. `ingest_frame` is called
    on every frame the detection loop already decodes (no extra capture),
    `start`/`extend` are called from the service's trigger paths, and
    `record_track` is called once per detected face while a clip is active.
    """

    def __init__(
        self,
        clips_root: Path,
        preroll_s: int = _DEFAULT_PREROLL_S,
        codec: str = _DEFAULT_CODEC,
        fps: float = _DEFAULT_FPS,
        ffmpeg_binary: str = "ffmpeg",
        clip_max_s: float = _DEFAULT_CLIP_MAX_S,
    ) -> None:
        if preroll_s < 0:
            raise ValueError("preroll_s must be zero or greater")
        if fps <= 0:
            raise ValueError("fps must be greater than zero")
        if clip_max_s <= 0:
            raise ValueError("clip_max_s must be greater than zero")
        self._clips_root = Path(clips_root)
        self._preroll_s = preroll_s
        self._codec = codec
        self._fps = fps
        self._ffmpeg_binary = ffmpeg_binary
        self._clip_max_s = clip_max_s
        self._queue_frames = max(_MIN_QUEUE_FRAMES, int(preroll_s * fps * _QUEUE_PREROLL_FACTOR))
        self._preroll: dict[str, deque[_PrerollFrame]] = {}
        self._active: dict[str, _ActiveClip] = {}
        self._lock = threading.Lock()

    # -- pre-roll buffer and frame intake -------------------------------------

    @property
    def ffmpeg_binary(self) -> str:
        return self._ffmpeg_binary

    @property
    def codec(self) -> str:
        return self._codec

    def ingest_frame(self, source_id: str, frame_bgr) -> None:
        """Feeds one decoded frame into source_id's ring buffer, and into its
        active recording if one is in progress. Never blocks and never
        triggers its own camera read."""
        now = monotonic()
        with self._lock:
            buffer = self._preroll.setdefault(source_id, deque())
            buffer.append(_PrerollFrame(captured_at=now, frame_bgr=frame_bgr))
            self._trim_preroll(buffer, now)
            active = self._active.get(source_id)
        if active is not None:
            self._offer(active, frame_bgr, now=now)

    def _trim_preroll(self, buffer: deque[_PrerollFrame], now: float) -> None:
        cutoff = now - self._preroll_s
        while buffer and buffer[0].captured_at < cutoff:
            buffer.popleft()

    def _offer(self, active: _ActiveClip, frame_bgr, now: float | None) -> None:
        """Queues one frame for the writer thread. `now` is given for live
        frames, which are ignored once the clip's end time has passed
        (a late close() must not lengthen the clip); seeded pre-roll frames
        pass None."""
        with active.lock:
            if active.closed:
                return
            if now is not None and now >= active.end_monotonic:
                return
            try:
                active.frames.put_nowait(frame_bgr)
            except queue.Full:
                active.frames_dropped += 1
                if active.frames_dropped == 1:
                    _log.warning(
                        "clip source_id=%s: writer queue full, dropping frames", active.source_id
                    )
                return
            active.frames_accepted += 1

    # -- recording lifecycle --------------------------------------------------

    def start(self, source_id: str, duration_s: int) -> str:
        """Begins a new clip for source_id seeded with the pre-roll buffer, or
        extends the one already in progress (one clip per camera at a time,
        requisito 31). Returns the clip_ref path either way.

        Seeding happens under the recorder lock so that a live frame arriving
        from another thread cannot slip in ahead of the older pre-roll frames.
        """
        with self._lock:
            existing = self._active.get(source_id)
            if existing is not None:
                self._extend(existing, duration_s)
                return existing.clip_ref

            active = self._open_clip(source_id, duration_s)
            self._active[source_id] = active
            buffer = self._preroll.get(source_id, deque())
            self._trim_preroll(buffer, monotonic())
            for preroll_frame in buffer:
                self._offer(active, preroll_frame.frame_bgr, now=None)
        return active.clip_ref

    def _open_clip(self, source_id: str, duration_s: int) -> _ActiveClip:
        camera_dir = self._clips_root / source_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        stem = self._unique_stem(camera_dir, now.strftime("%Y%m%dT%H%M%S"))
        clip_path = camera_dir / f"{stem}.mp4"
        tracks_path = camera_dir / f"{stem}{_TRACKS_SUFFIX}"
        started = monotonic()

        active = _ActiveClip(
            source_id=source_id,
            clip_ref=str(clip_path),
            clip_path=clip_path,
            tracks_path=tracks_path,
            tracks_handle=tracks_path.open("a", encoding="utf-8"),
            frames=queue.Queue(maxsize=self._queue_frames),
            end_monotonic=started + min(duration_s, self._clip_max_s),
            max_end_monotonic=started + self._clip_max_s,
            started_recording_at=now,
        )
        active.writer = threading.Thread(
            target=self._run_writer,
            args=(active,),
            name=f"clip-writer-{source_id}",
            daemon=True,
        )
        active.writer.start()
        return active

    @staticmethod
    def _unique_stem(camera_dir: Path, stem: str) -> str:
        """A second clip on the same source within the same second must not
        overwrite the first (ffmpeg runs with -y)."""
        candidate, attempt = stem, 1
        while (camera_dir / f"{candidate}.mp4").exists():
            attempt += 1
            candidate = f"{stem}_{attempt}"
        return candidate

    def _extend(self, active: _ActiveClip, duration_s: int) -> None:
        candidate_end = min(monotonic() + duration_s, active.max_end_monotonic)
        with active.lock:
            active.end_monotonic = max(active.end_monotonic, candidate_end)

    def extend(self, source_id: str, duration_s: int) -> None:
        """Pushes the end time of an in-progress clip further out, if one
        exists; a no-op otherwise (callers use `start` to begin one)."""
        with self._lock:
            existing = self._active.get(source_id)
        if existing is not None:
            self._extend(existing, duration_s)

    def is_recording(self, source_id: str) -> bool:
        with self._lock:
            return source_id in self._active

    def due_sources(self) -> list[str]:
        """Sources whose active clip has reached its end time, for a caller
        (the runner, or a periodic call from the service) to close.
        Read-only: does not itself close anything."""
        now = monotonic()
        with self._lock:
            actives = list(self._active.values())
        due: list[str] = []
        for active in actives:
            with active.lock:
                if active.end_monotonic <= now:
                    due.append(active.source_id)
        return due

    def close_due(self) -> list[str]:
        """Closes every clip whose end time has passed. Returns the clip_refs
        that produced a file."""
        closed: list[str] = []
        for source_id in self.due_sources():
            clip_ref = self.close(source_id)
            if clip_ref is not None:
                closed.append(clip_ref)
        return closed

    def close(self, source_id: str) -> str | None:
        """Stops the clip: lets the writer flush what is queued, closes
        ffmpeg's stdin so it finalizes the file, and closes the tracks file.
        Returns the clip_ref that was closed, or None if nothing was
        recording for source_id or if no frame ever reached the encoder (no
        file exists in that case)."""
        with self._lock:
            active = self._active.pop(source_id, None)
        if active is None:
            return None

        with active.lock:
            active.closed = True
            active.tracks_handle.close()
        self._stop_writer(active)
        return self._finalize(active)

    def close_all(self) -> None:
        with self._lock:
            source_ids = list(self._active)
        for source_id in source_ids:
            self.close(source_id)

    def _stop_writer(self, active: _ActiveClip) -> None:
        active.stop.set()
        writer = active.writer
        if writer is None:
            return
        writer.join(timeout=_WRITER_JOIN_TIMEOUT_S)
        if not writer.is_alive():
            return
        _log.warning(
            "clip source_id=%s: writer did not stop in time, killing ffmpeg", active.source_id
        )
        if active.process is not None:
            active.process.kill()
        writer.join(timeout=_KILLED_JOIN_TIMEOUT_S)

    def _finalize(self, active: _ActiveClip) -> str | None:
        if active.encoded_frames == 0 or not active.clip_path.exists():
            active.tracks_path.unlink(missing_ok=True)
            _log.warning(
                "clip source_id=%s: closed with zero frames encoded, no file produced",
                active.source_id,
            )
            return None
        make_private(active.clip_path)
        make_private(active.tracks_path)
        return active.clip_ref

    # -- tracks sidecar (requisito 31) ---------------------------------------

    def record_track(
        self, source_id: str, bbox: tuple[int, int, int, int], person_id: str | None
    ) -> None:
        """Appends one detection to the active clip's `.tracks.jsonl`, if a
        clip is in progress for source_id. A no-op otherwise, so callers can
        call this unconditionally on every detection. `t` is the timestamp of
        the most recent frame accepted for the clip, on the clip's own
        timeline (frame index divided by fps)."""
        with self._lock:
            active = self._active.get(source_id)
        if active is None:
            return
        with active.lock:
            if active.closed:
                return
            latest_index = max(0, active.frames_accepted - 1)
            record = {
                "t": round(latest_index / self._fps, 3),
                "bbox": list(bbox),
                "person_id": person_id,
            }
            try:
                active.tracks_handle.write(json.dumps(record) + "\n")
                active.tracks_handle.flush()
            except OSError as exc:
                _log.warning("clip source_id=%s: could not write track: %s", source_id, exc)

    # -- writer thread --------------------------------------------------------

    def _run_writer(self, active: _ActiveClip) -> None:
        """Runs until stop is set and the queue is empty, so a close() never
        loses frames that were already accepted."""
        while True:
            try:
                frame_bgr = active.frames.get(timeout=_WRITER_POLL_S)
            except queue.Empty:
                if active.stop.is_set():
                    break
                continue
            self._encode_frame(active, frame_bgr)
        self._finish_encoder(active)

    def _encode_frame(self, active: _ActiveClip, frame_bgr) -> None:
        if active.failed:
            return
        height, width = frame_bgr.shape[:2]
        if active.process is None and not self._start_encoder(active, width, height):
            return
        if active.frame_size != (width, height):
            # Raw video has no framing: a frame of another size would shift
            # every following byte and corrupt the clip, so it is skipped.
            _log.warning(
                "clip source_id=%s: skipping frame of size %sx%s, clip is %s",
                active.source_id,
                width,
                height,
                active.frame_size,
            )
            return
        self._pipe_frame(active, frame_bgr)

    def _start_encoder(self, active: _ActiveClip, width: int, height: int) -> bool:
        try:
            active.process = self._spawn_ffmpeg(active.clip_path, width, height)
        except PresenceUnavailableError as exc:
            # Seeing someone must never fail because recording did (SPEC.md
            # Reliability): the cause is logged once and the clip stays empty.
            active.failed = True
            _log.warning("clip source_id=%s: could not start ffmpeg: %s", active.source_id, exc)
            return False
        active.frame_size = (width, height)
        return True

    def _pipe_frame(self, active: _ActiveClip, frame_bgr) -> None:
        stdin = active.process.stdin if active.process is not None else None
        if stdin is None:
            active.failed = True
            return
        try:
            stdin.write(frame_bgr.tobytes())
        except (BrokenPipeError, OSError, ValueError) as exc:
            # ffmpeg died mid clip (disk full, killed externally). It must
            # never reach the detection loop; a truncated clip is the outcome.
            active.failed = True
            _log.warning("clip source_id=%s: write failed: %s", active.source_id, exc)
            return
        active.encoded_frames += 1

    def _finish_encoder(self, active: _ActiveClip) -> None:
        process = active.process
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                _log.warning("clip source_id=%s: stdin already closed", active.source_id)
        if wait_for_exit(process, _FFMPEG_EXIT_TIMEOUT_S):
            return
        _log.warning("clip source_id=%s: ffmpeg did not exit in time, killing", active.source_id)
        process.kill()

    def _spawn_ffmpeg(self, clip_path: Path, width: int, height: int) -> ProcessHandle:
        argv = self._ffmpeg_argv(clip_path, width, height)
        try:
            handle = spawn(argv, stdin=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise PresenceUnavailableError(
                "clip_recorder:ffmpeg",
                f"'{self._ffmpeg_binary}' was not found on PATH; install ffmpeg to record clips",
            ) from exc
        except OSError as exc:
            raise PresenceUnavailableError(
                "clip_recorder:ffmpeg", f"could not launch '{self._ffmpeg_binary}': {exc}"
            ) from exc
        if handle.stdin is None:
            handle.kill()
            raise PresenceUnavailableError(
                "clip_recorder:ffmpeg", "ffmpeg process has no stdin pipe"
            )
        return handle

    def _ffmpeg_argv(self, clip_path: Path, width: int, height: int) -> list[str]:
        return raw_video_argv(
            self._ffmpeg_binary, self._codec, self._fps, width, height, clip_path
        )


def raw_video_argv(
    ffmpeg_binary: str, codec: str, fps: float, width: int, height: int, output: Path
) -> list[str]:
    """ffmpeg command line that reads raw BGR frames from stdin and writes a
    silent, even sized video. Shared with render.py so a clip and its render
    are always encoded the same way."""
    return [
        ffmpeg_binary,
        "-y",
        "-loglevel",
        "error",
        "-nostats",
        "-f",
        "rawvideo",
        "-pixel_format",
        _RAW_PIXEL_FORMAT,
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-an",  # no audio input at all (requisito 31: audio off by default)
        "-vf",
        _EVEN_DIMENSIONS_FILTER,
        "-c:v",
        codec,
        "-pix_fmt",
        "yuv420p",
        str(output),
    ]


def wait_for_exit(process: ProcessHandle, timeout_s: float) -> bool:
    """True if the process exited within timeout_s."""
    deadline = monotonic() + timeout_s
    while process.poll() is None:
        if monotonic() >= deadline:
            return False
        sleep(_FFMPEG_EXIT_POLL_S)
    return True
