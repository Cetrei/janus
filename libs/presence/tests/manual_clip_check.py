from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

import cv2
import janus_biometrics
from janus_biometrics import ModelCache
from janus_biometrics.camera import Camera, CameraError, list_cameras

from janus_presence.clip_recorder import ClipRecorder
from janus_presence.index import PresenceIndex
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore

SOURCE_ID = "manual-clip-camera"
KEY_SIZE_BYTES = 32
WARMUP_FRAMES = 5
RATE_TOLERANCE = 0.15
DURATION_TOLERANCE_S = 0.5
PROCESS_TIMEOUT_S = 120
CLIPS_MAX_TOTAL_MB = 512
SNAPSHOT_RETENTION_S = 3600
EXPECTED_CODEC = "mpeg4"


@dataclass(frozen=True)
class CaptureStats:
    frames: int
    detections: int
    elapsed_s: float

    @property
    def rate(self) -> float:
        return self.frames / self.elapsed_s if self.elapsed_s > 0 else 0.0


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


class NullFrameSource:
    def capture_frame(self, camera_id: str) -> bytes:
        raise NotImplementedError(camera_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live check of ClipRecorder with a real camera and a real ffmpeg"
    )
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--duration", type=int, default=8)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--preroll", type=int, default=2)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--match", type=float, default=0.6)
    parser.add_argument("--ambiguous", type=float, default=1.2)
    return parser.parse_args()


def open_camera(index: int | None) -> Camera:
    if index is None:
        cameras = list_cameras()
        if not cameras:
            raise SystemExit("No camera found")
        index = cameras[0].index
    return Camera(index)


def make_model_cache() -> ModelCache:
    config = Path(janus_biometrics.__file__).parent / "models.yaml"
    return ModelCache(config_path=config, cache_dir=Path.home() / ".cache" / "janus-models")


def build_service(
    args: argparse.Namespace, workdir: Path, recorder: ClipRecorder
) -> PresenceService:
    return PresenceService(
        store=PresenceStore(workdir / "state", secrets.token_bytes(KEY_SIZE_BYTES)),
        index=PresenceIndex(),
        model_cache=make_model_cache(),
        frame_sources={SOURCE_ID: NullFrameSource()},
        match_threshold=args.match,
        match_threshold_ambiguous=args.ambiguous,
        clip_duration_s=args.duration,
        clips_root=workdir / "clips",
        clips_max_total_mb=CLIPS_MAX_TOTAL_MB,
        unknown_snapshot_retention_s=SNAPSHOT_RETENTION_S,
        snapshots_root=workdir / "snapshots",
        clip_recorder=recorder,
    )


def run_capture(
    service: PresenceService, camera: Camera, args: argparse.Namespace
) -> CaptureStats:
    for _ in range(WARMUP_FRAMES):
        camera.read()
    total = int(args.duration * args.fps)
    interval = 1.0 / args.fps
    detections = 0
    started = monotonic()
    next_tick = started
    for _ in range(total):
        ok, encoded = cv2.imencode(".jpg", camera.read())
        if ok and service.observe(SOURCE_ID, bytes(encoded)) is not None:
            detections += 1
        next_tick += interval
        sleep(max(0.0, next_tick - monotonic()))
    return CaptureStats(frames=total, detections=detections, elapsed_s=monotonic() - started)


def probe_clip(ffprobe: str, clip: Path) -> dict | None:
    if shutil.which(ffprobe) is None:
        return None
    argv = [
        ffprobe,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,nb_read_frames",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(clip),
    ]
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=PROCESS_TIMEOUT_S, check=False
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def decodes_cleanly(ffmpeg: str, clip: Path) -> Check:
    argv = [ffmpeg, "-v", "error", "-i", str(clip), "-f", "null", "-"]
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=PROCESS_TIMEOUT_S, check=False
    )
    clean = result.returncode == 0 and not result.stderr.strip()
    return Check("clip decodes with no errors", clean, result.stderr.strip()[:200])


def probe_checks(probe: dict, args: argparse.Namespace, stats: CaptureStats) -> list[Check]:
    stream = probe["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    frames = int(stream["nb_read_frames"])
    duration = float(probe["format"]["duration"])
    upper = stats.elapsed_s + args.preroll + DURATION_TOLERANCE_S
    codec = stream["codec_name"]
    return [
        Check(f"codec is {EXPECTED_CODEC}", codec == EXPECTED_CODEC, f"got {codec}"),
        Check("dimensions are even", width % 2 == 0 and height % 2 == 0, f"{width}x{height}"),
        Check(
            "container duration matches frames / fps",
            abs(duration - frames / args.fps) <= DURATION_TOLERANCE_S,
            f"{frames} frames, {duration:.2f}s",
        ),
        Check(
            "clip length is plausible for the capture",
            stats.elapsed_s * 0.5 <= duration <= upper,
            f"{duration:.2f}s clip, {stats.elapsed_s:.2f}s capture, {args.preroll}s preroll",
        ),
    ]


def read_tracks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def track_checks(path: Path, size: tuple[int, int] | None) -> list[Check]:
    rows = read_tracks(path)
    times = [row["t"] for row in rows]
    checks = [
        Check("tracks sidecar has entries", bool(rows), f"{len(rows)} tracks in {path.name}"),
        Check("tracks carry a person_id", all(row.get("person_id") for row in rows), ""),
        Check("track times never go backwards", times == sorted(times), ""),
    ]
    if size is not None and rows:
        width, height = size
        inside = all(
            x >= 0 and y >= 0 and x + w <= width and y + h <= height
            for x, y, w, h in (row["bbox"] for row in rows)
        )
        checks.append(Check("track boxes stay inside the frame", inside, f"{width}x{height}"))
    return checks


def clip_checks(clip: Path, args: argparse.Namespace, stats: CaptureStats) -> list[Check]:
    checks = [decodes_cleanly(args.ffmpeg, clip)]
    probe = probe_clip(args.ffprobe, clip)
    size = None
    if probe is None:
        checks.append(Check("ffprobe can read the clip", False, "ffprobe missing or failed"))
    else:
        checks.extend(probe_checks(probe, args, stats))
        stream = probe["streams"][0]
        size = (int(stream["width"]), int(stream["height"]))
    checks.extend(track_checks(clip.with_suffix(".tracks.jsonl"), size))
    return checks


def evaluate(workdir: Path, args: argparse.Namespace, stats: CaptureStats) -> int:
    clips = sorted((workdir / "clips" / SOURCE_ID).glob("*.mp4"))
    rate_ok = abs(stats.rate - args.fps) <= args.fps * RATE_TOLERANCE
    checks = [
        Check(
            "observe rate matches --fps",
            rate_ok,
            f"{stats.rate:.2f} fps measured, {args.fps} configured",
        ),
        Check(
            "a face was detected",
            stats.detections > 0,
            f"{stats.detections}/{stats.frames} frames",
        ),
        Check("a clip was produced", bool(clips), f"{len(clips)} file(s)"),
    ]
    if clips:
        checks.extend(clip_checks(clips[0], args, stats))
    print(f"\nOutput kept in {workdir}")
    return print_checks(checks)


def print_checks(checks: list[Check]) -> int:
    for check in checks:
        marker = " ok " if check.ok else "FAIL"
        suffix = f"  ({check.detail})" if check.detail else ""
        print(f"[{marker}] {check.name}{suffix}")
    return 0 if all(check.ok for check in checks) else 1


def main() -> int:
    args = parse_args()
    if shutil.which(args.ffmpeg) is None:
        print(f"'{args.ffmpeg}' was not found on PATH")
        return 1
    workdir = Path(tempfile.mkdtemp(prefix="janus-clip-check-"))
    recorder = ClipRecorder(
        workdir / "clips", preroll_s=args.preroll, fps=args.fps, ffmpeg_binary=args.ffmpeg
    )
    service = build_service(args, workdir, recorder)
    try:
        with open_camera(args.camera) as camera:
            print(f"Recording {args.duration}s at {args.fps} fps. Stay in front of the camera.")
            stats = run_capture(service, camera, args)
    except CameraError as exc:
        print(f"Camera error: {exc}")
        return 1
    finally:
        service.close()
    return evaluate(workdir, args, stats)


if __name__ == "__main__":
    raise SystemExit(main())
