"""Drawing helpers for a live detection preview: an animated bounding box
around a detected face (factory-vision style, but meant to look
deliberate rather than utilitarian), a zoom-in transition onto a face, and
a small data panel for whatever a caller wants to show next to it (name,
role, decision, etc).

Every function here takes a frame and returns a new frame; nothing is
stateful except AnimatedBox, whose whole job is to hold the small amount
of state an animation needs between frames (current corner positions,
pulse phase). This split exists so libs/presence can reuse these directly
in its own camera loop (see libs/presence/SPEC.md's mention of pausing a
clip at the recognized frame and showing a zoom+details overlay) without
depending on manual_camera_check.py or anything CLI-shaped.

Requires the `face-gui` extra (opencv-python), same as camera.py: this
module does drawing/compositing, which is unrelated to but bundled with
opencv's GUI build on PyPI. Never imported by providers/sface.py or
low_level.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# Colors are BGR (OpenCV convention), not RGB.
_COLOR_SEARCHING = (60, 200, 255)  # amber: face detected, not yet identified
_COLOR_LOCKED = (90, 220, 120)  # green: identified / verified
_COLOR_REJECTED = (70, 70, 230)  # red: rejected / low quality / liveness fail
_COLOR_PANEL_BG = (30, 24, 20)
_COLOR_TEXT = (235, 235, 235)

_CORNER_LEN_FRAC = 0.22  # corner-bracket length as a fraction of box side
_LERP_SPEED = 0.35  # how fast the box eases toward its target each frame (0-1)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass
class AnimatedBox:
    """Eases a bounding box toward wherever detection last put it, instead
    of snapping frame to frame, plus a slow pulse used for the "searching"
    state. One instance tracks one on-screen box across frames; a caller
    tracking several faces holds one AnimatedBox per face.
    """

    x: float
    y: float
    w: float
    h: float
    _pulse: float = field(default=0.0, repr=False)

    @classmethod
    def at(cls, x: float, y: float, w: float, h: float) -> AnimatedBox:
        return cls(x=x, y=y, w=w, h=h)

    def update(self, target: tuple[float, float, float, float]) -> None:
        tx, ty, tw, th = target
        self.x = _lerp(self.x, tx, _LERP_SPEED)
        self.y = _lerp(self.y, ty, _LERP_SPEED)
        self.w = _lerp(self.w, tw, _LERP_SPEED)
        self.h = _lerp(self.h, th, _LERP_SPEED)
        self._pulse = (self._pulse + 0.08) % (2 * np.pi)

    def as_int_box(self) -> tuple[int, int, int, int]:
        return int(self.x), int(self.y), int(self.w), int(self.h)

    @property
    def pulse_alpha(self) -> float:
        """0..1, breathing pulse for the "searching" (not yet locked) state."""
        return 0.5 + 0.5 * float(np.sin(self._pulse))


def draw_corner_brackets(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    color: tuple[int, int, int] = _COLOR_SEARCHING,
    thickness: int = 3,
    alpha: float = 1.0,
) -> np.ndarray:
    """Draws four L-shaped corner brackets around `box`, factory-vision
    style, rather than a plain rectangle: brackets read as "actively
    tracking this" rather than a static crop marker, and leave the
    detected subject unobscured. `alpha` blends the brackets onto the
    frame (used for the searching-state pulse); 1.0 draws at full opacity.
    """
    x, y, w, h = box
    corner_len = max(int(min(w, h) * _CORNER_LEN_FRAC), 12)

    overlay = frame.copy()
    corners = [
        ((x, y), (1, 1)),  # top-left: draw right and down
        ((x + w, y), (-1, 1)),  # top-right: draw left and down
        ((x, y + h), (1, -1)),  # bottom-left: draw right and up
        ((x + w, y + h), (-1, -1)),  # bottom-right: draw left and up
    ]
    for (cx, cy), (dx, dy) in corners:
        cv2.line(overlay, (cx, cy), (cx + dx * corner_len, cy), color, thickness, cv2.LINE_AA)
        cv2.line(overlay, (cx, cy), (cx, cy + dy * corner_len), color, thickness, cv2.LINE_AA)

    if alpha >= 1.0:
        return overlay
    return cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)


def draw_scan_line(
    frame: np.ndarray, box: tuple[int, int, int, int], phase: float, *, color=_COLOR_SEARCHING
) -> np.ndarray:
    """A horizontal line sweeping up and down inside `box`, phase in
    0..2*pi (feed AnimatedBox._pulse-style state in). Reads as "actively
    scanning", the factory-belt cue the user asked for, without needing a
    photograph-realistic animation."""
    x, y, w, h = box
    sweep = (np.sin(phase) + 1) / 2  # 0..1
    line_y = int(y + sweep * h)
    overlay = frame.copy()
    cv2.line(overlay, (x, line_y), (x + w, line_y), color, 2, cv2.LINE_AA)
    return cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)


def draw_data_panel(
    frame: np.ndarray,
    anchor: tuple[int, int],
    lines: list[str],
    *,
    title: str | None = None,
) -> np.ndarray:
    """Draws a small translucent panel with `lines` of text, anchored with
    its top-left corner at `anchor`. Generic on purpose (list[str] in, no
    biometrics-specific fields) so libs/presence can pass name/role/
    decision, and this stays useful for other spokes too.
    """
    x, y = anchor
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    line_height = 22
    padding = 10

    all_lines = ([title] if title else []) + lines
    text_widths = [
        cv2.getTextSize(line, font, font_scale, 1)[0][0] for line in all_lines
    ]
    panel_w = max(text_widths, default=100) + padding * 2
    panel_h = len(all_lines) * line_height + padding * 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + panel_w, y + panel_h), _COLOR_PANEL_BG, -1)
    blended = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)

    text_y = y + padding + line_height - 6
    if title:
        cv2.putText(
            blended, title, (x + padding, text_y), font, font_scale, _COLOR_LOCKED, 1, cv2.LINE_AA
        )
        text_y += line_height
    for line in lines:
        cv2.putText(
            blended, line, (x + padding, text_y), font, font_scale, _COLOR_TEXT, 1, cv2.LINE_AA
        )
        text_y += line_height
    return blended


def zoom_to_face(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    progress: float,
    *,
    margin_frac: float = 0.6,
) -> np.ndarray:
    """Crops progressively tighter around `box` as `progress` goes 0..1,
    then scales back up to the original frame size (a digital dolly-zoom),
    for the "pauses and zooms into the face" moment the user asked for.
    progress=0 returns the frame unchanged; progress=1 returns a tight
    crop around the face (padded by margin_frac of the box size) scaled up
    to fill the frame.
    """
    progress = max(0.0, min(1.0, progress))
    frame_h, frame_w = frame.shape[:2]
    x, y, w, h = box
    margin_x, margin_y = int(w * margin_frac), int(h * margin_frac)
    target_x0 = max(x - margin_x, 0)
    target_y0 = max(y - margin_y, 0)
    target_x1 = min(x + w + margin_x, frame_w)
    target_y1 = min(y + h + margin_y, frame_h)

    # Interpolate crop bounds from the full frame (progress=0) to the
    # target box (progress=1), rather than jump-cutting, so the transition
    # reads as a zoom rather than a swap.
    x0 = int(_lerp(0, target_x0, progress))
    y0 = int(_lerp(0, target_y0, progress))
    x1 = int(_lerp(frame_w, target_x1, progress))
    y1 = int(_lerp(frame_h, target_y1, progress))
    x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
    x1, y1 = min(x1, frame_w), min(y1, frame_h)

    cropped = frame[y0:y1, x0:x1]
    return cv2.resize(cropped, (frame_w, frame_h), interpolation=cv2.INTER_LINEAR)


def state_color(state: str) -> tuple[int, int, int]:
    """Maps a coarse detection state to its bracket color. `state` is one
    of "searching", "locked", "rejected" -- kept as plain strings rather
    than an enum so presence/other callers don't need to import an enum
    from a GUI-only module just to call this."""
    return {
        "searching": _COLOR_SEARCHING,
        "locked": _COLOR_LOCKED,
        "rejected": _COLOR_REJECTED,
    }.get(state, _COLOR_SEARCHING)
