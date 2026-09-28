"""Manual END-TO-END check of the real biometrics stack: live camera + live
microphone -> enroll -> identify -> remember across processes. NOT a pytest
file: it needs a human in front of real hardware.

Unlike manual_camera_check.py (which exercises each provider in isolation
and stores plaintext JSON), this drives the same objects the core will use:

    build_default_registry -> BiometricService -> EncryptedTemplateStore
    (SFace + YuNet + MiniFASNet for face, WeSpeaker via sherpa-onnx for voice)

Templates are stored AES-256-GCM encrypted under tests/.manual_e2e_check/,
with a key generated on first use. Every verification is appended to
history.jsonl (decision/reason only, never a score, requisito 16), so a
NEW process can prove it "remembers": run `status` in a fresh terminal.

Setup, from libs/biometrics/ (uv sync is exact: this REPLACES the `face`
extra with `face-gui`, which is what you want, the two must not coexist):

    uv sync --extra face-gui --extra sensors --extra voice

On Wayland, if the preview flickers or Qt complains:

    QT_QPA_PLATFORM=xcb uv run python tests/manual_e2e_check.py ...

Usage:

    uv run python tests/manual_e2e_check.py doctor    # deps + downloads and verifies every model
    uv run python tests/manual_e2e_check.py enroll    # face (5 photos) + voice (5 utterances)
    uv run python tests/manual_e2e_check.py verify    # face + voice -> identity verdict
    uv run python tests/manual_e2e_check.py run       # enroll whatever is missing, then verify
    uv run python tests/manual_e2e_check.py status    # what is enrolled + recent verifications
    uv run python tests/manual_e2e_check.py reset --yes

Options: --camera <index> (auto-detected when exactly one), --mic <index|name>.

`doctor` is what downloads the models: ModelCache fetches each url entry in
models.yaml on first resolve and refuses any file whose sha256 differs, so
nothing here trusts a download it has not verified.

Voice thresholds are the conservative uncalibrated defaults (0.7/0.5). Run
`python -m janus_biometrics calibrate --kind voice` for real ones. Face
decisions come from SFaceFaceVerifier, which still uses its own built-in
thresholds (already flagged as a separate finding).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

# manual_camera_check.py lives next to this file, and doubles as the source
# of the live-preview/recording helpers reused below. Importing it also puts
# src/ on sys.path and exits with an install hint if opencv (face-gui) is
# missing, so the janus_biometrics imports that follow are safe.
sys.path.insert(0, str(Path(__file__).parent))
import manual_camera_check as cam  # noqa: E402, I001
import cv2  # noqa: E402

from janus_biometrics import _face_pipeline as pipeline  # noqa: E402
from janus_biometrics.base import BiometricResult, Decision  # noqa: E402
from janus_biometrics.defaults import build_default_registry  # noqa: E402
from janus_biometrics.enrollment import (  # noqa: E402
    MIN_FACE_SAMPLES,
    MIN_VOICE_SAMPLES,
    enroll_face,
    enroll_voice,
)
from janus_biometrics.errors import BiometricsError  # noqa: E402
from janus_biometrics.models import ModelCache  # noqa: E402
from janus_biometrics.policy import Thresholds  # noqa: E402
from janus_biometrics.providers.speaker_wespeaker import SherpaWeSpeakerExtractor  # noqa: E402
from janus_biometrics.sensors import MicrophoneSource, SensorConfig  # noqa: E402
from janus_biometrics.service import BiometricService  # noqa: E402
from janus_biometrics.store import EncryptedTemplateStore  # noqa: E402
from janus_platform.paths import write_private  # noqa: E402

_STATE_DIR = Path(__file__).parent / ".manual_e2e_check"
_KEY_FILE = _STATE_DIR / "biometrics.key"
_HISTORY_FILE = _STATE_DIR / "history.jsonl"
_PROFILE = "owner"
_KEY_SIZE_BYTES = 32  # AES-256
_UTTERANCE_S = 4.0  # above enrollment's 3.0s floor and verification's 2.5s floor
_HISTORY_TAIL = 10
_KINDS = ("face", "voice")
_REQUIRED_MODELS = ("yunet", "sface", "minifasnet_v2", "minifasnet_v1se", "wespeaker")
# BiometricService requires face thresholds, but SFaceFaceVerifier does not
# consume them yet; kept explicit so the wiring is honest about it.
_FACE_THRESHOLDS = Thresholds(t_high=0.7, t_low=0.5)
_VOICE_THRESHOLDS = Thresholds(t_high=0.7, t_low=0.5)


# --------------------------------------------------------------- plumbing


def _parse_device(raw: str | None) -> str | int | None:
    if raw is None:
        return None
    return int(raw) if raw.isdigit() else raw


def _ensure_key() -> bytes:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not _KEY_FILE.exists():
        write_private(_KEY_FILE, secrets.token_bytes(_KEY_SIZE_BYTES))
        print(f"Generated a new template key at {_KEY_FILE}")
    return _KEY_FILE.read_bytes()


def _open_store() -> EncryptedTemplateStore:
    return EncryptedTemplateStore(_STATE_DIR, _ensure_key())


def _build_service(cache: ModelCache, store: EncryptedTemplateStore) -> BiometricService:
    registry = build_default_registry(cache, voice_thresholds=_VOICE_THRESHOLDS)
    return BiometricService(
        registry=registry,
        store=store,
        face_thresholds=_FACE_THRESHOLDS,
        voice_thresholds=_VOICE_THRESHOLDS,
        face_provider_ref="local",
        voice_provider_ref="local",
    )


def _make_microphone(device: str | int | None) -> MicrophoneSource:
    return MicrophoneSource(SensorConfig(id="e2e-mic", kind="microphone", device=device))


def _record_event(kind: str, result: BiometricResult) -> None:
    """Append-only log of what was decided, never the score (requisito 16)."""
    event = {
        "at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "decision": str(result.decision),
        "liveness": str(result.liveness),
        "reason": result.reason,
        "model_id": result.model_id,
    }
    with _HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


# ------------------------------------------------------------------ doctor


def _check_module(module: str, extra: str) -> bool:
    # A real import, not importlib.util.find_spec: find_spec only proves the
    # package exists on disk, so it reported sherpa_onnx as fine while the
    # actual import (native library load) failed later during enroll.
    try:
        importlib.import_module(module)
    except ImportError as exc:
        print(f"  [FAIL] {module}: {exc!r} (missing? uv sync --extra {extra})")
        return False
    print(f"  [ ok ] {module}")
    return True


def _check_models(cache: ModelCache) -> bool:
    print("Models (downloaded on first use, sha256-verified every time):")
    all_ok = True
    for model_id in _REQUIRED_MODELS:
        try:
            cache.resolve(model_id)
            print(f"  [ ok ] {model_id}")
        except BiometricsError as exc:
            print(f"  [FAIL] {model_id}: {exc}")
            all_ok = False
    return all_ok


def _check_hardware() -> bool:
    cameras = cam.list_cameras()
    print(f"  [{' ok ' if cameras else 'FAIL'}] cameras found: {len(cameras)}")
    if importlib.util.find_spec("sounddevice") is None:
        return bool(cameras)
    import sounddevice as sd

    inputs = [
        f"{index}: {device['name']}"
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
    ]
    print(f"  [{' ok ' if inputs else 'FAIL'}] input devices: {inputs or 'none'}")
    return bool(cameras) and bool(inputs)


def cmd_doctor(_args: argparse.Namespace) -> int:
    print("Dependencies:")
    deps_ok = all(
        [
            _check_module("cv2", "face-gui"),
            _check_module("sherpa_onnx", "voice"),
            _check_module("sounddevice", "sensors"),
        ]
    )
    models_ok = _check_models(cam._make_cache())
    print("Hardware:")
    hardware_ok = _check_hardware()
    healthy = deps_ok and models_ok and hardware_ok
    print("\nReady for enroll/verify." if healthy else "\nFix the [FAIL] items above first.")
    return 0 if healthy else 1


# ------------------------------------------------------------------ enroll


def _enroll_face(
    cache: ModelCache, store: EncryptedTemplateStore, camera_index: int | None
) -> None:
    camera = cam._open_camera(camera_index)
    images: list[bytes] = []
    try:
        detector = cam._bootstrap_detector(cache, camera)
        while len(images) < MIN_FACE_SAMPLES:
            prompt = f"Enroll face {len(images) + 1}/{MIN_FACE_SAMPLES} (vary angle a little)"
            captured = cam._live_capture(camera, detector, prompt)
            if captured is None:
                raise SystemExit("Aborted by user.")
            image, face, _box = captured
            quality_ok, reason = pipeline.check_quality(pipeline.decode_image(image), face)
            if not quality_ok:
                print(f"  quality check failed ({reason}), try again.")
                continue
            images.append(image)
            print(f"  face capture {len(images)}/{MIN_FACE_SAMPLES} OK")
    finally:
        camera.close()
        cv2.destroyAllWindows()
    enrollment = enroll_face(images, cache)
    store.save(enrollment)
    print(f"Face enrolled: {enrollment.samples} samples, model_id={enrollment.model_id}")


def _enroll_voice(
    cache: ModelCache, store: EncryptedTemplateStore, mic_device: str | int | None
) -> None:
    extractor = SherpaWeSpeakerExtractor(cache.resolve("wespeaker"))
    mic = _make_microphone(mic_device)
    print("Voice: speak a full natural sentence for the whole recording, a new one each time.")
    recordings = [
        cam._record_voice_sample(mic, _UTTERANCE_S, f"Enroll voice {i + 1}/{MIN_VOICE_SAMPLES}")
        for i in range(MIN_VOICE_SAMPLES)
    ]
    enrollment = enroll_voice(recordings, extractor, model_id=cam._VOICE_MODEL_ID)
    store.save(enrollment)
    print(f"Voice enrolled: {enrollment.samples} samples, model_id={enrollment.model_id}")


def _enroll_kinds(kinds: list[str], args: argparse.Namespace) -> None:
    cache = cam._make_cache()
    store = _open_store()
    if "face" in kinds:
        _enroll_face(cache, store, args.camera)
    if "voice" in kinds:
        _enroll_voice(cache, store, _parse_device(args.mic))


def cmd_enroll(args: argparse.Namespace) -> int:
    kinds = list(_KINDS) if args.only == "both" else [args.only]
    _enroll_kinds(kinds, args)
    print("\nDone. Encrypted templates saved. Try: verify")
    return 0


# ------------------------------------------------------------------ verify


def _show_face_result(camera, image: bytes, box, result: BiometricResult) -> None:
    lines = [
        f"decision:  {result.decision}",
        f"liveness:  {result.liveness}",
        f"reason:    {result.reason}",
    ]
    frame = pipeline.decode_image(image)
    cam._play_zoom_and_hold(camera, frame, box, lines, panel_title=f"[{result.decision}]")


async def _verify_face_live(
    service: BiometricService, cache: ModelCache, camera_index: int | None
) -> BiometricResult:
    camera = cam._open_camera(camera_index)
    try:
        detector = cam._bootstrap_detector(cache, camera)
        captured = cam._live_capture(camera, detector, "Verify face")
        if captured is None:
            raise SystemExit("Aborted by user.")
        image, _face, box = captured
        result = await service.verify_face(image, profile=_PROFILE)
        _show_face_result(camera, image, box, result)
        return result
    finally:
        camera.close()
        cv2.destroyAllWindows()


async def _verify_voice_live(
    service: BiometricService, mic_device: str | int | None
) -> BiometricResult:
    audio = cam._record_voice_sample(_make_microphone(mic_device), _UTTERANCE_S, "Verify voice")
    return await service.verify_voice(audio, profile=_PROFILE)


async def _verify_all(args: argparse.Namespace) -> dict[str, BiometricResult]:
    cache = cam._make_cache()
    service = _build_service(cache, _open_store())
    results: dict[str, BiometricResult] = {}
    try:
        if not args.skip_face:
            results["face"] = await _verify_face_live(service, cache, args.camera)
        if not args.skip_voice:
            results["voice"] = await _verify_voice_live(service, _parse_device(args.mic))
    finally:
        await service.close()
    for kind, result in results.items():
        _record_event(kind, result)
    return results


def _verdict(results: dict[str, BiometricResult]) -> str:
    decisions = [result.decision for result in results.values()]
    if not decisions:
        return "NOTHING VERIFIED"
    if Decision.LOW in decisions:
        return "REJECTED (at least one signal contradicts the enrolled owner)"
    if all(decision == Decision.HIGH for decision in decisions):
        return "IDENTIFIED (" + " + ".join(results) + ")"
    if Decision.HIGH in decisions:
        return "PARTIAL (one signal confirmed, the rest inconclusive or medium)"
    return "INCONCLUSIVE"


def _print_results(results: dict[str, BiometricResult], verdict: str) -> None:
    print("\n--- Results (scores are never exposed, requisito 16) ---")
    for kind, result in results.items():
        print(
            f"{kind:>5}: {result.decision:<12} liveness={result.liveness:<11} "
            f"reason={result.reason} model={result.model_id}"
        )
    print(f"\nVERDICT: {verdict}")


def cmd_verify(args: argparse.Namespace) -> int:
    results = asyncio.run(_verify_all(args))
    verdict = _verdict(results)
    _print_results(results, verdict)
    return 0 if verdict.startswith("IDENTIFIED") else 1


def cmd_run(args: argparse.Namespace) -> int:
    store = _open_store()
    skipped = {"face": args.skip_face, "voice": args.skip_voice}
    missing = [k for k in _KINDS if not skipped[k] and not store.exists(k, _PROFILE)]
    if missing:
        print(f"Not enrolled yet: {', '.join(missing)}. Enrolling first.\n")
        _enroll_kinds(missing, args)
    return cmd_verify(args)


# ---------------------------------------------------------- status / reset


def _read_history_tail() -> list[str]:
    if not _HISTORY_FILE.exists():
        return []
    return _HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-_HISTORY_TAIL:]


def _print_enrolled(store: EncryptedTemplateStore) -> None:
    print("Enrolled templates (read from disk, decrypted with the stored key):")
    found = False
    for kind in _KINDS:
        enrollment = store.load(kind, _PROFILE)
        if enrollment is None:
            print(f"  {kind}: not enrolled")
            continue
        found = True
        print(
            f"  {kind}: {enrollment.samples} samples, model_id={enrollment.model_id}, "
            f"enrolled {enrollment.created_at.isoformat()}"
        )
    if not found:
        print("  (nothing yet, run: enroll)")


def _print_history() -> None:
    lines = _read_history_tail()
    print(f"\nLast {len(lines)} verifications remembered:")
    for line in lines:
        event = json.loads(line)
        print(
            f"  {event['at']}  {event['kind']:>5}  {event['decision']:<12} "
            f"liveness={event['liveness']} reason={event['reason']}"
        )
    if not lines:
        print("  (none yet)")


def cmd_status(_args: argparse.Namespace) -> int:
    _print_enrolled(_open_store())
    _print_history()
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("This securely deletes the enrolled face/voice templates. Re-run with --yes.")
        return 1
    store = _open_store()
    for kind in _KINDS:
        store.delete(kind, _PROFILE)
    print("Templates deleted (overwritten before unlink). History and key were kept.")
    return 0


# -------------------------------------------------------------------- main


def _add_verify_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skip-face", action="store_true", help="Do not use the camera")
    parser.add_argument("--skip-voice", action="store_true", help="Do not use the microphone")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual end-to-end biometrics check")
    parser.add_argument(
        "--camera", type=int, default=None, help="Camera index (manual_camera_check.py list)"
    )
    parser.add_argument("--mic", default=None, help="Microphone device index or name")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check deps, download and verify models, probe hardware")
    enroll = sub.add_parser("enroll", help="Enroll face and/or voice into the encrypted store")
    enroll.add_argument("--only", choices=["face", "voice", "both"], default="both")
    _add_verify_flags(sub.add_parser("verify", help="Verify face + voice and print a verdict"))
    _add_verify_flags(sub.add_parser("run", help="Enroll what is missing, then verify"))
    sub.add_parser("status", help="Show enrolled templates and remembered verifications")
    reset = sub.add_parser("reset", help="Securely delete enrolled templates")
    reset.add_argument("--yes", action="store_true")
    return parser


_COMMANDS = {
    "doctor": cmd_doctor,
    "enroll": cmd_enroll,
    "verify": cmd_verify,
    "run": cmd_run,
    "status": cmd_status,
    "reset": cmd_reset,
}


def main() -> int:
    args = build_parser().parse_args()
    try:
        return _COMMANDS[args.command](args)
    except BiometricsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
