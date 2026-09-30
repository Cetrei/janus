"""Manual, real-hardware test tool for the local:sface chain (YuNet + SFace
+ MiniFASNetV2/V1SE). NOT a pytest file: this is meant to be run directly
by a human sitting in front of the camera, since no automated test can
drive real camera hardware or judge whether a real live face was shown to
it.

Requires the `face-gui` extra, NOT `face`:

    uv sync --extra face-gui

(opencv-python-headless, installed by the `face` extra used by
production/tests, has no GUI support and on Linux often ships without
real V4L2 capture either -- see camera.py's module docstring.)

Usage (from libs/biometrics/):

    uv run python tests/manual_camera_check.py list      # list available cameras
    uv run python tests/manual_camera_check.py enroll     # capture 5 photos, build enrollment
    uv run python tests/manual_camera_check.py verify     # capture 1 photo, verify it

`enroll`/`verify` auto-detect the camera when --camera is omitted: if
exactly one real camera is found, it is used directly; if more than one
is found, you are asked to pick with --camera <index>. Do not assume
index 0 is your camera -- on Linux especially, V4L2 often exposes
several device nodes per physical camera (a metadata-only node alongside
the real capture node), so the working index can be 2, 3, or anything
else; OpenCV's "can't open camera by index" warnings for the indices
that are not yours are expected noise from that probing, not an error.

Both `enroll` and `verify` show a live preview with an animated detection
overlay (amber scanning brackets while searching, green once a face is
framed) rather than a single still frame, then pause on a zoomed-in crop
of the captured face with a data panel showing the result -- reusing
camera.py/overlay.py, the same modules libs/presence is meant to reuse for
its own multi-camera, clip-pause-and-zoom UI (see libs/presence/SPEC.md).

`enroll` stores the resulting embeddings as a plaintext JSON enrollment
under tests/.manual_camera_check/owner.json (NOT the real encrypted store
in store.py: this tool is for testing the model chain in isolation, not
for producing a real Janus enrollment).

Voice subcommands (`enroll-voice`/`verify-voice`) exercise the real
MicrophoneSource (sensors.py) + WeSpeakerVerifier/SherpaWeSpeakerExtractor
(providers/speaker_wespeaker.py) chain, the voice counterpart of
enroll/verify above. Like those, this stores a plaintext test enrollment
under tests/.manual_camera_check/owner_voice.json, NOT the real encrypted
store. Unlike face's live camera preview, there is no equivalent live
audio-level meter here (out of scope for this manual tool): each capture
is a fixed-duration blocking recording with a countdown printed to the
console, immediately followed by the enroll/verify result -- if a capture
comes back too short or silent, the fix is to run the subcommand again
and speak sooner/louder, not a feature this script needs to add.

Requires the `sensors` extra (sounddevice/PortAudio) AND the `voice`
extra (sherpa-onnx) from libs/biometrics/:

    uv sync --extra sensors --extra voice

and a real `wespeaker` entry in models.yaml (see models.yaml's own
comments and providers/speaker_wespeaker.py's module docstring for the
one-time manual step of downloading the .onnx weights and filling in a
verified sha256 -- this script does not work around that, it surfaces
the same BiometricsError _make_voice_extractor's equivalent in __main__.py
raises if that entry is still the unfilled template).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

try:
    import cv2
except ImportError:
    print(
        "opencv (with GUI support) is not installed. Run:\n"
        "  uv sync --extra face-gui\n"
        "from libs/biometrics/ first. Note: this is `face-gui`, not `face` --\n"
        "the headless build used for tests/production has no GUI support.",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from janus_biometrics import _face_pipeline as pipeline  # noqa: E402
from janus_biometrics import overlay  # noqa: E402
from janus_biometrics.base import Enrollment  # noqa: E402
from janus_biometrics.camera import (  # noqa: E402
    Camera,
    CameraError,
    list_cameras,
    print_camera_list,
)
from janus_biometrics.enrollment import enroll_voice  # noqa: E402
from janus_biometrics.errors import (  # noqa: E402
    BiometricsError,
    EnrollmentError,
    SensorUnavailable,
)
from janus_biometrics.models import ModelCache  # noqa: E402
from janus_biometrics.policy import Thresholds  # noqa: E402
from janus_biometrics.providers.sface import SFaceFaceVerifier  # noqa: E402
from janus_biometrics.providers.speaker_wespeaker import (  # noqa: E402
    SherpaWeSpeakerExtractor,
    WeSpeakerVerifier,
)
from janus_biometrics.sensors import MicrophoneSource, SensorConfig  # noqa: E402

_MODELS_YAML = Path(__file__).parent.parent / "src" / "janus_biometrics" / "models.yaml"
_STATE_DIR = Path(__file__).parent / ".manual_camera_check"
_ENROLLMENT_PATH = _STATE_DIR / "owner.json"
_MODEL_ID = "sface-yunet-minifasnet-v1"

_VOICE_ENROLLMENT_PATH = _STATE_DIR / "owner_voice.json"
_VOICE_MODEL_ID = "wespeaker-resnet34-v1"
_VOICE_SAMPLE_COUNT = 5  # matches enrollment.MIN_VOICE_SAMPLES
_VOICE_UTTERANCE_S = 4.0  # above enrollment.MIN_VOICE_UTTERANCE_S (3.0s), with margin
_VOICE_VERIFY_S = 4.0  # above the wespeaker provider's own too_short floor (2.5s), with margin
# Conservative bench-style defaults, same reasoning __main__.py's own
# _cmd_bench uses for --kind voice: this script has no calibrate step of
# its own (unlike cmd_enroll's face path, which only ever produces
# embeddings for later use by the real `python -m janus_biometrics
# calibrate` command, not a live decision here) -- HIGH/MEDIUM/LOW still
# needs *some* Thresholds to report a decision at all in cmd_verify_voice.
_VOICE_THRESHOLDS = Thresholds(t_high=0.7, t_low=0.5)

_WINDOW_TITLE = "Janus - biometrics preview"
_ZOOM_DURATION_S = 0.6
_HOLD_AFTER_ZOOM_S = 1.2


def _make_cache() -> ModelCache:
    return ModelCache(config_path=_MODELS_YAML, cache_dir=Path.home() / ".cache" / "janus-models")


def _open_camera(index: int | None) -> Camera:
    """Opens a camera. If `index` is None (the user did not pass
    --camera), auto-detects: probes for real cameras and uses the only
    one found, or asks the user to pick with --camera if there is more
    than one. Never guesses index 0, since on Linux especially the first
    working capture index is frequently not 0 (V4L2 often exposes
    metadata-only device nodes before the real capture node -- exactly
    what happened on this machine, where the real camera is index 3).
    """
    if index is None:
        print("No --camera given, detecting automatically...")
        cameras = list_cameras()
        if not cameras:
            print(
                "No camera found. Run 'list' for details, or check the "
                "camera is connected.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if len(cameras) > 1:
            print_camera_list(cameras, file=sys.stderr)
            print(
                "\nMore than one camera found; pick one with --camera <index>.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        index = cameras[0].index
        print(f"Using camera {index} ({cameras[0].width}x{cameras[0].height}).")
    try:
        cam = Camera(index=index)
        cam.open()
        return cam
    except CameraError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


def _play_zoom_and_hold(
    cam: Camera, frame, box: tuple[int, int, int, int], panel_lines: list[str], panel_title: str
) -> None:
    """Freezes on `frame`, zooms into `box` over _ZOOM_DURATION_S, then
    holds the zoomed result with the data panel for _HOLD_AFTER_ZOOM_S.
    This is the "pauses where it was recognized and zooms in" beat the
    preview reuses from what libs/presence is meant to do with a
    recognition clip later.
    """
    steps = 20
    for i in range(steps + 1):
        progress = i / steps
        zoomed = overlay.zoom_to_face(frame, box, progress)
        shown = overlay.draw_data_panel(zoomed, (20, 20), panel_lines, title=panel_title)
        cv2.imshow(_WINDOW_TITLE, shown)
        if cv2.waitKey(int(_ZOOM_DURATION_S * 1000 / steps)) & 0xFF == 27:
            return

    hold_until = time.monotonic() + _HOLD_AFTER_ZOOM_S
    final = overlay.draw_data_panel(
        overlay.zoom_to_face(frame, box, 1.0), (20, 20), panel_lines, title=panel_title
    )
    while time.monotonic() < hold_until:
        cv2.imshow(_WINDOW_TITLE, final)
        if cv2.waitKey(30) & 0xFF == 27:
            return


def _live_capture(
    cam: Camera,
    detector,
    prompt: str,
) -> tuple[bytes, object, tuple[int, int, int, int]] | None:
    """Shows a live preview with an animated detection overlay until the
    user presses SPACE (capture) or ESC (abort/None). While no face is
    detected, brackets pulse amber with a scanning line; once exactly one
    face is framed, brackets turn solid green to signal "ready to
    capture". Returns (png_bytes, raw_face_detection, int_box) for the
    frame captured, or None if aborted.
    """
    box_anim: overlay.AnimatedBox | None = None
    print(f"[{prompt}] SPACE to capture, ESC to abort.")
    while True:
        frame = cam.read()
        faces = pipeline.detect_faces(detector, frame)
        shown = frame.copy()
        shown = overlay.draw_data_panel(shown, (20, 20), [prompt, "SPACE: capture   ESC: abort"])

        ready = False
        target_box = None
        target_face = None
        if len(faces) == 1:
            x, y, w, h = faces[0][:4].astype(int)
            target_box = (x, y, w, h)
            target_face = faces[0]
            ready = True

        if target_box is not None:
            if box_anim is None:
                box_anim = overlay.AnimatedBox.at(*target_box)
            else:
                box_anim.update(target_box)
            int_box = box_anim.as_int_box()
            color = overlay.state_color("locked" if ready else "searching")
            shown = overlay.draw_corner_brackets(shown, int_box, color=color)
        else:
            box_anim = None

        cv2.imshow(_WINDOW_TITLE, shown)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            return None
        if key == 32 and ready:  # SPACE, only accepted once a single face is framed
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                print("Failed to encode captured frame.", file=sys.stderr)
                raise SystemExit(1)
            return encoded.tobytes(), target_face, target_box
        if key == 32 and not ready:
            print(
                "  need exactly one face framed before capturing "
                f"(currently seeing {len(faces)})."
            )


def cmd_list(_args: argparse.Namespace) -> None:
    print("Probing camera indices... (this briefly opens each one)")
    cameras = list_cameras()
    print_camera_list(cameras)
    if cameras:
        print(
            "\nUse --camera <index> with 'enroll' or 'verify' to pick one "
            "(future: libs/presence is expected to run against several of "
            "these at once, see libs/presence/SPEC.md)."
        )


def cmd_enroll(args: argparse.Namespace) -> None:
    cache = _make_cache()
    cam = _open_camera(args.camera)
    embeddings: list[list[float]] = []
    try:
        detector = None
        recognizer = None
        i = 0
        while i < 5:
            if detector is None:
                detector = _bootstrap_detector(cache, cam)
                recognizer = pipeline.create_recognizer(str(cache.resolve("sface")))
            captured = _live_capture(cam, detector, f"Enroll {i + 1}/5")
            if captured is None:
                raise SystemExit("Aborted by user.")
            image, face, _box = captured

            frame = pipeline.decode_image(image)
            quality_ok, reason = pipeline.check_quality(frame, face)
            if not quality_ok:
                print(f"  capture {i + 1}: quality check failed ({reason}). Retrying.")
                continue
            embedding = pipeline.embed_face(recognizer, frame, face)
            embeddings.append(embedding)
            print(f"  capture {i + 1}/5 OK")
            i += 1
    finally:
        cam.close()
        cv2.destroyAllWindows()

    if len(embeddings) < 3:
        print(
            f"Only got {len(embeddings)} good captures out of 5 attempts; "
            "need at least 3 to build a usable centroid. Try again with "
            "better lighting / closer to the camera.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    dim = len(embeddings[0])
    centroid = [sum(vec[i] for vec in embeddings) / len(embeddings) for i in range(dim)]

    enrollment = Enrollment(
        kind="face",
        profile="owner",
        model_id=_MODEL_ID,
        dim=dim,
        embeddings=embeddings,
        centroid=centroid,
        samples=len(embeddings),
    )
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _ENROLLMENT_PATH.write_text(
        json.dumps(
            {
                "kind": enrollment.kind,
                "profile": enrollment.profile,
                "model_id": enrollment.model_id,
                "dim": enrollment.dim,
                "embeddings": enrollment.embeddings,
                "centroid": enrollment.centroid,
                "samples": enrollment.samples,
                "created_at": enrollment.created_at.isoformat(),
            }
        )
    )
    print(f"\nEnrolled with {len(embeddings)} samples -> {_ENROLLMENT_PATH}")
    print("This is a plaintext test file, NOT the real encrypted Janus store.")


def _bootstrap_detector(cache: ModelCache, cam: Camera):
    frame = cam.read()
    return pipeline.create_detector(str(cache.resolve("yunet")), frame.shape[:2])


def cmd_verify(args: argparse.Namespace) -> None:
    if not _ENROLLMENT_PATH.exists():
        print(
            f"No enrollment found at {_ENROLLMENT_PATH}. Run 'enroll' first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    data = json.loads(_ENROLLMENT_PATH.read_text())
    from datetime import datetime

    enrollment = Enrollment(
        kind=data["kind"],
        profile=data["profile"],
        model_id=data["model_id"],
        dim=data["dim"],
        embeddings=data["embeddings"],
        centroid=data["centroid"],
        samples=data["samples"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )

    cache = _make_cache()
    cam = _open_camera(args.camera)
    try:
        detector = _bootstrap_detector(cache, cam)
        captured = _live_capture(cam, detector, "Verify")
        if captured is None:
            print("Aborted by user.")
            return
        image, _face, box = captured

        verifier = SFaceFaceVerifier(model_cache=cache)
        try:
            result = asyncio.run(verifier.verify(image, enrollment))
        finally:
            asyncio.run(verifier.close())

        frame = pipeline.decode_image(image)
        state = "locked" if result.decision.name == "HIGH" else "rejected"
        panel_lines = [
            f"decision:  {result.decision}",
            f"liveness:  {result.liveness}",
            f"quality:   {result.quality_ok}",
            f"reason:    {result.reason}",
        ]
        _play_zoom_and_hold(cam, frame, box, panel_lines, panel_title=f"[{state.upper()}]")

        print("\n--- BiometricResult ---")
        print(f"decision:    {result.decision}")
        print(f"liveness:    {result.liveness}")
        print(f"quality_ok:  {result.quality_ok}")
        print(f"reason:      {result.reason}")
        print(f"provider_id: {result.provider_id}")
        print(f"model_id:    {result.model_id}")
        print(
            "\nNote: `score` is never exposed by BiometricResult by design "
            "(requisito 16, see base.py) -- only the decision/reason above."
        )
    finally:
        cam.close()
        cv2.destroyAllWindows()


def _make_voice_extractor() -> SherpaWeSpeakerExtractor:
    """Resolves the `wespeaker` model entry the same way __main__.py's own
    _make_voice_extractor does, and raises the same clear BiometricsError
    (via ModelCache/ModelSourceError) if the operator has not yet filled
    in models.yaml's template entry -- this script does not duplicate
    that error message, it just surfaces whatever ModelCache.resolve()
    itself raises.
    """
    cache = _make_cache()
    model_path = cache.resolve("wespeaker")
    return SherpaWeSpeakerExtractor(model_path)


def _record_voice_sample(mic: MicrophoneSource, seconds: float, prompt: str):
    """Blocking capture with a console countdown -- this script's stand-in
    for the live camera preview's animated overlay, since there is no
    equivalent visual feedback loop for audio here (see module docstring).
    Raises SensorUnavailable if the device cannot be opened/captured from
    (MicrophoneSource.capture_audio's own contract, propagated as-is).
    """
    print(f"[{prompt}] recording for {seconds:.0f}s starting in...")
    for remaining in (3, 2, 1):
        print(f"  {remaining}...")
        time.sleep(1)
    print("  Speak now.")
    audio = mic.capture_audio(max_s=seconds)
    print("  done.")
    return audio


def cmd_enroll_voice(args: argparse.Namespace) -> None:
    mic = MicrophoneSource(SensorConfig(id="manual-check-mic", kind="microphone", device=args.mic))
    try:
        extractor = _make_voice_extractor()
    except BiometricsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

    recordings = []
    i = 0
    while i < _VOICE_SAMPLE_COUNT:
        try:
            audio = _record_voice_sample(
                mic, _VOICE_UTTERANCE_S, f"Enroll {i + 1}/{_VOICE_SAMPLE_COUNT}"
            )
        except SensorUnavailable as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        recordings.append(audio)
        print(f"  capture {i + 1}/{_VOICE_SAMPLE_COUNT} OK")
        i += 1

    try:
        enrollment = enroll_voice(recordings, extractor, model_id=_VOICE_MODEL_ID)
    except EnrollmentError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _VOICE_ENROLLMENT_PATH.write_text(
        json.dumps(
            {
                "kind": enrollment.kind,
                "profile": enrollment.profile,
                "model_id": enrollment.model_id,
                "dim": enrollment.dim,
                "embeddings": enrollment.embeddings,
                "centroid": enrollment.centroid,
                "samples": enrollment.samples,
                "created_at": enrollment.created_at.isoformat(),
            }
        )
    )
    print(f"\nEnrolled with {enrollment.samples} samples -> {_VOICE_ENROLLMENT_PATH}")
    print("This is a plaintext test file, NOT the real encrypted Janus store.")


def cmd_verify_voice(args: argparse.Namespace) -> None:
    if not _VOICE_ENROLLMENT_PATH.exists():
        print(
            f"No voice enrollment found at {_VOICE_ENROLLMENT_PATH}. Run 'enroll-voice' first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    data = json.loads(_VOICE_ENROLLMENT_PATH.read_text())
    from datetime import datetime

    enrollment = Enrollment(
        kind=data["kind"],
        profile=data["profile"],
        model_id=data["model_id"],
        dim=data["dim"],
        embeddings=data["embeddings"],
        centroid=data["centroid"],
        samples=data["samples"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )

    mic = MicrophoneSource(SensorConfig(id="manual-check-mic", kind="microphone", device=args.mic))
    try:
        extractor = _make_voice_extractor()
    except BiometricsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

    try:
        audio = _record_voice_sample(mic, _VOICE_VERIFY_S, "Verify")
    except SensorUnavailable as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

    verifier = WeSpeakerVerifier(
        feature_extractor=extractor,
        thresholds=_VOICE_THRESHOLDS,
        liveness_mode="off",  # requisito 10: no voice anti-spoofing in v1
    )
    try:
        result = asyncio.run(verifier.verify(audio, enrollment))
    finally:
        asyncio.run(verifier.close())

    print("\n--- BiometricResult ---")
    print(f"decision:    {result.decision}")
    print(f"liveness:    {result.liveness}")
    print(f"quality_ok:  {result.quality_ok}")
    print(f"reason:      {result.reason}")
    print(f"provider_id: {result.provider_id}")
    print(f"model_id:    {result.model_id}")
    print(
        "\nNote: `score` is never exposed by BiometricResult by design "
        "(requisito 16, see base.py) -- only the decision/reason above."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Camera index to use (see 'list'). If omitted, auto-detects "
        "when exactly one camera is found.",
    )
    parser.add_argument(
        "--mic",
        default=None,
        help="Microphone device index or name (see sounddevice.query_devices() "
        "for what your system exposes). If omitted, uses sounddevice's own "
        "default input device.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List cameras OpenCV can actually open on this machine.")
    sub.add_parser("enroll", help="Capture 5 photos and store a test enrollment.")
    sub.add_parser("verify", help="Capture 1 photo and verify against the test enrollment.")
    sub.add_parser(
        "enroll-voice", help="Record 5 utterances and store a test voice enrollment."
    )
    sub.add_parser(
        "verify-voice", help="Record 1 utterance and verify against the test voice enrollment."
    )
    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "enroll":
        cmd_enroll(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "enroll-voice":
        cmd_enroll_voice(args)
    elif args.command == "verify-voice":
        cmd_verify_voice(args)


if __name__ == "__main__":
    main()
