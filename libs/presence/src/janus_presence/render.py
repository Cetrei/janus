"""Render of a raw clip (SPEC.md ampliacion 2026-09-27, requisito 32).

`ClipRecorder` leaves two files per clip: the raw video and the
`.tracks.jsonl` sidecar (time, bbox, person_id per detection). This module
turns those two into a separate file that zooms in on the face and shows a
panel with the name, the role and the time:

* **Raw and render stay apart.** The identity can arrive late (the owner
  names someone after the clip was recorded), the render costs CPU, and the
  raw clip can be rendered again with another style. So the render is never
  produced by the recorder, and it always uses the identity the store holds
  at the moment it runs.
* **Alignment comes from the sidecar.** A track's `t` is the timestamp of
  the frame it belongs to on the clip's own timeline, so the frame at index
  `i` looks up tracks with `t <= i / fps`. This is why the recorder's fps
  has to be the real rate of `observe` (see clip_recorder.py, Known limit).
* **The zoom follows, it does not jump.** The focus box is eased between
  frames, the zoom level moves a fixed step per frame toward its target, and
  the last face stays in focus for `hold_s` after the tracks stop, so the
  video does not flicker between full frame and close up.
* **The drawing is biometrics' `overlay`** (brackets, zoom, data panel), not
  a second copy of it. It is imported inside the frame composer so this
  module can be imported, and its pure parts tested, without OpenCV.
* **Atomic output.** The video is encoded to `<name>.partial.mp4` and moved
  into place only when ffmpeg exits cleanly, so a crash never leaves a
  truncated file under the final name.

Known limit: the clock on the panel is the clip's start time (taken from its
file name, which is the moment of the trigger) plus the frame's offset. The
first frames of a clip are pre-roll recorded before that moment, so the
shown time can be ahead of the real one by up to `preroll_s`.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from janus_platform.paths import make_private
from janus_platform.process import ProcessHandle, spawn

from janus_presence.clip_recorder import raw_video_argv, wait_for_exit
from janus_presence.errors import ClipNotFoundError, PresenceError, PresenceUnavailableError

_log = logging.getLogger(__name__)

_TRACKS_SUFFIX = ".tracks.jsonl"
_PARTIAL_SUFFIX = ".partial.mp4"
_STEM_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"
_STEM_TIMESTAMP_LENGTH = 15
_FFMPEG_EXIT_TIMEOUT_S = 30.0

_BOX_EASING = 0.35  # how far the focus box moves toward its target each frame
_PANEL_MARGIN_PX = 12
_PANEL_LINE_PX = 22
_PANEL_PADDING_PX = 20
_UNNAMED_TITLE = "Unknown"

_DEFAULT_CODEC = "mpeg4"
_DEFAULT_ZOOM = 0.7
_DEFAULT_HOLD_S = 1.0
_DEFAULT_ZOOM_STEP = 0.15

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class TrackPoint:
    t: float
    bbox: Box
    person_id: str | None


@dataclass(frozen=True)
class Identity:
    """What the panel shows about a person. Resolved by the caller at render
    time, so this module never touches the store."""

    label: str | None
    role: str | None
    known: bool


IdentityResolver = Callable[[str], Identity | None]


@dataclass(frozen=True)
class RenderStyle:
    """zoom: 0 keeps the full frame, 1 is the tightest crop on the face.
    hold_s: how long the last face stays in focus after its tracks stop.
    zoom_step: zoom level gained or lost per frame, so the move reads as a
    dolly and not as a cut."""

    zoom: float = _DEFAULT_ZOOM
    hold_s: float = _DEFAULT_HOLD_S
    zoom_step: float = _DEFAULT_ZOOM_STEP
    codec: str = _DEFAULT_CODEC
    brackets: bool = True
    panel: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.zoom <= 1.0:
            raise ValueError("zoom must be between 0 and 1")
        if self.hold_s < 0:
            raise ValueError("hold_s must be zero or greater")
        if not 0.0 < self.zoom_step <= 1.0:
            raise ValueError("zoom_step must be greater than 0 and at most 1")


# -- pure helpers (no OpenCV, no ffmpeg) ---------------------------------------


def tracks_path_for(clip_ref: str | Path) -> Path:
    return Path(clip_ref).with_suffix(_TRACKS_SUFFIX)


def render_path_for(clip_ref: str | Path, renders_root: Path) -> Path:
    """Where a clip's render goes: a tree of its own next to the clips, so the
    two have independent retention (requisito 32)."""
    clip = Path(clip_ref)
    return Path(renders_root) / clip.parent.name / clip.name


def clip_started_at(clip_ref: str | Path) -> datetime | None:
    """The trigger time encoded in the clip's file name (`20260929T012833`,
    optionally followed by `_2`), or None if the name does not follow it."""
    stem = Path(clip_ref).stem[:_STEM_TIMESTAMP_LENGTH]
    try:
        return datetime.strptime(stem, _STEM_TIMESTAMP_FORMAT)
    except ValueError:
        return None


def load_tracks(path: Path) -> list[TrackPoint]:
    """Reads the sidecar, oldest first. A missing file is an empty list (a
    clip with no faces has no sidecar entries). A line that does not parse is
    skipped with a warning: a crash mid write leaves a truncated last line,
    and one bad line must not make the whole clip unrenderable."""
    if not path.exists():
        return []
    points: list[TrackPoint] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            x, y, w, h = (int(v) for v in record["bbox"])
            points.append(TrackPoint(float(record["t"]), (x, y, w, h), record.get("person_id")))
        except (ValueError, KeyError, TypeError) as exc:
            _log.warning("%s line %d skipped, not a valid track: %s", path.name, number, exc)
    return sorted(points, key=lambda point: point.t)


def focus_at(tracks: list[TrackPoint], t: float, hold_s: float) -> TrackPoint | None:
    """The face the render should center on at time `t`: the most recent track
    at or before `t` and no older than `hold_s`. Several faces at the same
    instant: the biggest one, which is the closest to the camera. Boxes with
    no area (a face fully outside the frame) are never a focus."""
    candidates = [
        point
        for point in tracks
        if point.t <= t and t - point.t <= hold_s and point.bbox[2] > 0 and point.bbox[3] > 0
    ]
    if not candidates:
        return None
    latest = max(point.t for point in candidates)
    newest = [point for point in candidates if point.t == latest]
    return max(newest, key=lambda point: point.bbox[2] * point.bbox[3])


def ease_box(
    current: tuple[float, ...], target: tuple[float, ...], factor: float
) -> tuple[float, ...]:
    return tuple(c + (goal - c) * factor for c, goal in zip(current, target, strict=True))


def step_toward(value: float, target: float, step: float) -> float:
    if value < target:
        return min(value + step, target)
    return max(value - step, target)


def _clock_text(started_at: datetime | None, t: float) -> str:
    if started_at is None:
        return f"t+{t:.1f}s"
    return (started_at + timedelta(seconds=t)).strftime("%H:%M:%S")


# -- frame composition (needs OpenCV through biometrics' overlay) -----------------


class _FrameComposer:
    """Turns a raw frame and the time it sits at into the rendered frame. Holds
    the small state a smooth zoom needs between frames."""

    def __init__(
        self,
        tracks: list[TrackPoint],
        resolver: IdentityResolver,
        style: RenderStyle,
        started_at: datetime | None,
    ) -> None:
        self._tracks = tracks
        self._resolver = resolver
        self._style = style
        self._started_at = started_at
        self._identities: dict[str, Identity | None] = {}
        self._box: tuple[float, ...] | None = None
        self._identity: Identity | None = None
        self._progress = 0.0

    def compose(self, frame, t: float):
        focus = focus_at(self._tracks, t, self._style.hold_s)
        target = self._style.zoom if focus is not None else 0.0
        self._progress = step_toward(self._progress, target, self._style.zoom_step)
        if focus is not None:
            self._follow(focus)
        elif self._progress == 0.0:
            self._box = None
        if self._box is None:
            return frame
        return self._draw(frame, focus, t)

    def _follow(self, focus: TrackPoint) -> None:
        target = tuple(float(v) for v in focus.bbox)
        self._box = target if self._box is None else ease_box(self._box, target, _BOX_EASING)
        self._identity = self._identity_for(focus.person_id)

    def _identity_for(self, person_id: str | None) -> Identity | None:
        if person_id is None:
            return None
        if person_id not in self._identities:
            self._identities[person_id] = self._resolver(person_id)
        return self._identities[person_id]

    def _draw(self, frame, focus: TrackPoint | None, t: float):
        from janus_biometrics import overlay

        box = tuple(int(v) for v in self._box)
        known = self._identity is not None and self._identity.known
        out = frame
        if focus is not None and self._style.brackets:
            state = "locked" if known else "searching"
            out = overlay.draw_corner_brackets(out, box, color=overlay.state_color(state))
        if self._progress > 0.0:
            out = overlay.zoom_to_face(out, box, self._progress)
        if focus is not None and self._style.panel:
            out = self._draw_panel(out, overlay, t)
        return out

    def _draw_panel(self, frame, overlay, t: float):
        identity = self._identity
        title = identity.label if identity is not None and identity.label else _UNNAMED_TITLE
        lines = []
        if identity is not None and identity.role:
            lines.append(f"role: {identity.role}")
        lines.append(_clock_text(self._started_at, t))
        panel_h = (len(lines) + 1) * _PANEL_LINE_PX + _PANEL_PADDING_PX
        anchor = (_PANEL_MARGIN_PX, max(frame.shape[0] - panel_h - _PANEL_MARGIN_PX, 0))
        return overlay.draw_data_panel(frame, anchor, lines, title=title)


# -- ffmpeg and the render loop ---------------------------------------------------


def _require_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise PresenceUnavailableError(
            "render:opencv",
            "opencv is required to render clips; install janus-presence[camera]",
        ) from exc
    return cv2


def _spawn_encoder(argv: list[str]) -> ProcessHandle:
    binary = argv[0]
    try:
        handle = spawn(argv, stdin=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise PresenceUnavailableError(
            "render:ffmpeg", f"'{binary}' was not found on PATH; install ffmpeg to render clips"
        ) from exc
    except OSError as exc:
        raise PresenceUnavailableError(
            "render:ffmpeg", f"could not launch '{binary}': {exc}"
        ) from exc
    if handle.stdin is None:
        handle.kill()
        raise PresenceUnavailableError("render:ffmpeg", "ffmpeg process has no stdin pipe")
    return handle


def _write_frame(encoder: ProcessHandle, frame) -> None:
    try:
        encoder.stdin.write(frame.tobytes())
    except (BrokenPipeError, OSError, ValueError) as exc:
        raise PresenceUnavailableError("render:ffmpeg", f"write failed: {exc}") from exc


def _finish_encoder(encoder: ProcessHandle) -> None:
    try:
        encoder.stdin.close()
    except OSError:
        _log.warning("render: ffmpeg stdin was already closed")
    if not wait_for_exit(encoder, _FFMPEG_EXIT_TIMEOUT_S):
        encoder.kill()
        raise PresenceUnavailableError("render:ffmpeg", "ffmpeg did not exit in time")
    if encoder.poll() != 0:
        code = encoder.poll()
        raise PresenceUnavailableError("render:ffmpeg", f"ffmpeg exited with code {code}")


def _encode_video(
    clip: Path, target: Path, composer: _FrameComposer, style: RenderStyle, ffmpeg_binary: str
) -> None:
    cv2 = _require_cv2()
    capture = cv2.VideoCapture(str(clip))
    encoder: ProcessHandle | None = None
    try:
        if not capture.isOpened():
            raise PresenceUnavailableError("render:decoder", f"cannot open {clip.name}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            raise PresenceUnavailableError("render:decoder", f"{clip.name} reports no frame rate")
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            composed = composer.compose(frame, index / fps)
            if encoder is None:
                height, width = composed.shape[:2]
                argv = raw_video_argv(ffmpeg_binary, style.codec, fps, width, height, target)
                encoder = _spawn_encoder(argv)
            _write_frame(encoder, composed)
            index += 1
        if encoder is None:
            raise PresenceError(f"{clip.name} has no decodable frames, nothing to render")
        _finish_encoder(encoder)
    finally:
        capture.release()
        if encoder is not None:
            encoder.kill()  # a no-op once ffmpeg has exited


def render_clip(
    clip_ref: str | Path,
    output_path: str | Path,
    resolver: IdentityResolver,
    *,
    style: RenderStyle | None = None,
    ffmpeg_binary: str = "ffmpeg",
) -> str:
    """Renders `clip_ref` with a zoom on the face and a name, role and time
    panel, into `output_path`, and returns that path. `resolver` maps a
    person_id to what the panel shows, so the caller decides which identity is
    current. Raises ClipNotFoundError for a missing clip and
    PresenceUnavailableError when OpenCV, the decoder or ffmpeg cannot do the
    job; in every failure nothing is left under `output_path`."""
    style = style or RenderStyle()
    clip = Path(clip_ref)
    if not clip.is_file():
        raise ClipNotFoundError(str(clip))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}{_PARTIAL_SUFFIX}")
    composer = _FrameComposer(
        load_tracks(tracks_path_for(clip)), resolver, style, clip_started_at(clip)
    )
    try:
        _encode_video(clip, partial, composer, style, ffmpeg_binary)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(output)
    make_private(output)
    return str(output)
