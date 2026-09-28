"""python -m janus_biometrics CLI (requisito 19, 26): enroll, list, delete,
keygen, calibrate, bench.

This CLI wires together enrollment.py, store.py, models.py, and bench.py
against real hardware/files -- it does not add any new biometric logic of
its own. Voice subcommands (enroll --kind voice, and bench/calibrate for
voice) need the `wespeaker` entry in models.yaml, which is a template
until the operator fills in a verified sha256 (see models.yaml's own
comments and providers/speaker_wespeaker.py's module docstring) -- once
that entry is real, `_make_voice_extractor` below resolves it the same
way `_cmd_bench` already resolves `sface`/`yunet` for face.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

from janus_biometrics import enrollment
from janus_biometrics.base import Enrollment, PcmAudio
from janus_biometrics.bench import BenchReport, bench_verifier
from janus_biometrics.errors import BiometricsError
from janus_biometrics.models import ModelCache
from janus_biometrics.policy import Thresholds
from janus_biometrics.providers.sface import SFaceFaceVerifier
from janus_biometrics.providers.speaker_wespeaker import (
    SherpaWeSpeakerExtractor,
    WeSpeakerVerifier,
)
from janus_biometrics.store import EncryptedTemplateStore
from janus_platform.paths import default_state_dir, write_private

_KEY_SIZE_BYTES = 32  # AES-256 (requisito 17)


def _default_models_yaml() -> Path:
    return Path(__file__).parent / "models.yaml"


def _load_key(key_file: Path) -> bytes:
    if not key_file.exists():
        raise BiometricsError(
            f"No key found at {key_file}. Run 'python -m janus_biometrics keygen' first, "
            "or set JANUS_BIOMETRICS_KEY_FILE to an existing key file."
        )
    return key_file.read_bytes()


def _open_store(args: argparse.Namespace) -> EncryptedTemplateStore:
    key = _load_key(Path(args.key_file))
    return EncryptedTemplateStore(Path(args.state_dir), key)


def _read_wav_files(source: Path) -> list[PcmAudio]:
    """--source dir for --kind voice: every .wav file in the directory,
    sorted by name for reproducibility, decoded to PcmAudio (16-bit mono
    16 kHz, base.PcmAudio's own contract). Rejects any file that is not
    already in that exact format rather than silently resampling: a
    silent resample here could mask a recording setup that will not match
    what MicrophoneSource captures at verification time (also always
    16-bit mono 16 kHz, see sensors.py), and a mismatch is much cheaper to
    catch here than to debug from unexplained low scores later.
    """
    import wave

    if not source.is_dir():
        raise BiometricsError(f"--source must be a directory of .wav files, got: {source}")
    paths = sorted(p for p in source.iterdir() if p.is_file() and p.suffix == ".wav")
    if not paths:
        raise BiometricsError(f"No .wav files found in {source}")

    recordings: list[PcmAudio] = []
    for path in paths:
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise BiometricsError(
                    f"{path}: expected 16-bit mono PCM, got "
                    f"{wav_file.getnchannels()} channel(s) at "
                    f"{wav_file.getsampwidth() * 8}-bit"
                )
            if wav_file.getframerate() != 16_000:
                raise BiometricsError(
                    f"{path}: expected 16 kHz sample rate, got {wav_file.getframerate()} Hz"
                )
            samples = wav_file.readframes(wav_file.getnframes())
        recordings.append(PcmAudio(samples=samples, sample_rate=16_000))
    return recordings


def _make_voice_extractor(state_dir: Path) -> SherpaWeSpeakerExtractor:
    """Resolves the `wespeaker` model entry (models.yaml) and builds the
    real sherpa-onnx-backed extractor. Raises BiometricsError with a clear
    message (via ModelCache/ModelSourceError) if the operator has not yet
    filled in the template entry -- see models.yaml's own comments and
    providers/speaker_wespeaker.py's module docstring for that one-time
    manual step.
    """
    model_cache = ModelCache(_default_models_yaml(), state_dir / "models")
    model_path = model_cache.resolve("wespeaker")
    return SherpaWeSpeakerExtractor(model_path)


def _read_single_wav(path: Path) -> PcmAudio:
    """Reads exactly one .wav file (--sample for --kind voice bench).
    Duplicates _read_wav_files's format validation for the single-file
    case rather than adding an `only` parameter there: bench's --sample
    is one specific file the caller names, not "every .wav in a
    directory" (enroll/calibrate's contract), so the two should not share
    a signature just to avoid a few duplicated lines."""
    import wave

    if not path.is_file():
        raise BiometricsError(f"--sample must be a .wav file, got: {path}")
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise BiometricsError(
                f"{path}: expected 16-bit mono PCM, got "
                f"{wav_file.getnchannels()} channel(s) at "
                f"{wav_file.getsampwidth() * 8}-bit"
            )
        if wav_file.getframerate() != 16_000:
            raise BiometricsError(
                f"{path}: expected 16 kHz sample rate, got {wav_file.getframerate()} Hz"
            )
        samples = wav_file.readframes(wav_file.getnframes())
    return PcmAudio(samples=samples, sample_rate=16_000)


def _read_images(source: Path) -> list[bytes]:
    """--source dir: every file in the directory, sorted by name for
    reproducibility. Camera capture (--source device) is intentionally not
    wired here: it needs a real SensorSource + a live preview loop
    (overlay.py already exists for that), which is an interactive flow a
    non-interactive CLI command should not silently attempt -- v1 of this
    command supports the fully-scriptable, testable path (a directory of
    pre-captured images) and documents device capture as a follow-up
    rather than guessing at a UX for it."""
    if not source.is_dir():
        raise BiometricsError(f"--source must be a directory of images, got: {source}")
    paths = sorted(p for p in source.iterdir() if p.is_file())
    if not paths:
        raise BiometricsError(f"No files found in {source}")
    return [p.read_bytes() for p in paths]


def _cmd_keygen(args: argparse.Namespace) -> int:
    key_file = Path(args.key_file)
    if key_file.exists() and not args.force:
        print(f"Key already exists at {key_file}. Use --force to overwrite.", file=sys.stderr)
        return 1
    key = secrets.token_bytes(_KEY_SIZE_BYTES)
    write_private(key_file, key)
    print(f"Wrote a new 256-bit key to {key_file}")
    return 0


def _cmd_enroll(args: argparse.Namespace) -> int:
    store = _open_store(args)
    if args.kind == "face":
        images = _read_images(Path(args.source))
        model_cache = ModelCache(_default_models_yaml(), Path(args.state_dir) / "models")
        enrollment_result = enrollment.enroll_face(images, model_cache)
    else:
        recordings = _read_wav_files(Path(args.source))
        extractor = _make_voice_extractor(Path(args.state_dir))
        enrollment_result = enrollment.enroll_voice(
            recordings, extractor, model_id="wespeaker-resnet34-v1"
        )
    store.save(enrollment_result)
    print(
        f"Enrolled {enrollment_result.kind}/{enrollment_result.profile}: "
        f"{enrollment_result.samples} samples, model_id={enrollment_result.model_id}"
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    store = _open_store(args)
    found = False
    for kind in ("face", "voice"):
        for profile in (args.profile,) if args.profile else ("owner",):
            if store.exists(kind, profile):
                enrolled: Enrollment = store.load(kind, profile)
                print(
                    f"{kind}/{profile}: model_id={enrolled.model_id} "
                    f"samples={enrolled.samples} created_at={enrolled.created_at.isoformat()}"
                )
                found = True
    if not found:
        print("No enrollments found.")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    store = _open_store(args)
    if not store.exists(args.kind, args.profile):
        print(f"No enrollment for {args.kind}/{args.profile}.")
        return 1
    store.delete(args.kind, args.profile)
    print(f"Deleted {args.kind}/{args.profile} (overwritten before unlink).")
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    store = _open_store(args)
    existing = store.load(args.kind, args.profile)
    if existing is None:
        raise BiometricsError(
            f"No enrollment for {args.kind}/{args.profile}; enroll before calibrating."
        )

    impostor_embeddings = None
    if args.impostors:
        if args.kind == "face":
            model_cache = ModelCache(_default_models_yaml(), Path(args.state_dir) / "models")
            impostor_images = _read_images(Path(args.impostors))
            impostor_embeddings = []
            for image in impostor_images:
                from janus_biometrics.low_level import detect_and_embed_faces

                for face_embedding in detect_and_embed_faces(image, model_cache):
                    impostor_embeddings.append(face_embedding.embedding)
        else:
            extractor = _make_voice_extractor(Path(args.state_dir))
            impostor_recordings = _read_wav_files(Path(args.impostors))
            impostor_embeddings = [extractor.embed(audio) for audio in impostor_recordings]

    result = enrollment.calibrate(
        existing.embeddings,
        target_frr=args.target_frr,
        impostor_embeddings=impostor_embeddings,
        target_far=args.target_far,
    )

    print(f"Calibration for {args.kind}/{args.profile}:")
    print(f"  t_high = {result.t_high:.4f}")
    print(f"  t_low  = {result.t_low:.4f}")
    print(f"  genuine scores (leave-one-out): {[round(s, 3) for s in result.genuine_scores]}")
    if result.impostor_scores is not None:
        print(f"  impostor scores: {[round(s, 3) for s in result.impostor_scores]}")
        print(f"  target FAR={result.target_far:.1%} target FRR={result.target_frr:.1%}")
    else:
        print(
            "  No impostor samples given: thresholds are conservative defaults, "
            "still calibration_recommended."
        )
    print(
        f"\nApply with: biometrics.{args.kind}.thresholds = "
        f"{{ high = {result.t_high:.4f}, low = {result.t_low:.4f} }}"
    )
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    store = _open_store(args)
    enrolled = store.load(args.kind, args.profile)
    if enrolled is None:
        raise BiometricsError(
            f"No {args.kind} enrollment for profile '{args.profile}'; enroll before running bench."
        )
    if not args.sample:
        raise BiometricsError(f"--sample <{'image' if args.kind == 'face' else 'wav'} file> is required to bench {args.kind} verification")

    if args.kind == "face":
        model_cache = ModelCache(_default_models_yaml(), Path(args.state_dir) / "models")
        verifier = SFaceFaceVerifier(model_cache=model_cache, liveness_mode="off")
        sample = Path(args.sample).read_bytes()
    else:
        extractor = _make_voice_extractor(Path(args.state_dir))
        # bench measures latency, not decision quality: conservative
        # calibration_recommended defaults are fine here, same reasoning
        # _cmd_calibrate's own "no impostor samples given" branch already
        # documents for the no-impostors case.
        verifier = WeSpeakerVerifier(
            feature_extractor=extractor,
            thresholds=Thresholds(t_high=0.7, t_low=0.5),
            liveness_mode="off",
        )
        sample = _read_single_wav(Path(args.sample))

    async def run_once() -> None:
        await verifier.verify(sample, enrolled)

    result = asyncio.run(
        bench_verifier(
            kind=args.kind,
            provider_id=verifier.id,
            model_id=enrolled.model_id,
            run_once=run_once,
            iterations=args.iterations,
        )
    )
    report = BenchReport(results=[result])
    print(report.render())
    return 1 if report.any_degraded else 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-dir",
        default=str(default_state_dir()),
        help="Base state directory (default: platform default state dir)",
    )
    parser.add_argument(
        "--key-file",
        default=str(default_state_dir() / "biometrics.key"),
        help="Path to the 256-bit template encryption key",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m janus_biometrics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen", help="Generate a new 256-bit template key")
    _add_common_args(keygen)
    keygen.add_argument("--force", action="store_true", help="Overwrite an existing key")
    keygen.set_defaults(func=_cmd_keygen)

    enroll = subparsers.add_parser("enroll", help="Enroll a face or voice template")
    _add_common_args(enroll)
    enroll.add_argument("--kind", choices=["face", "voice"], required=True)
    enroll.add_argument("--profile", default="owner")
    enroll.add_argument(
        "--source",
        required=True,
        help="Directory of sample images/recordings (device capture not yet wired, see --help)",
    )
    enroll.set_defaults(func=_cmd_enroll)

    list_cmd = subparsers.add_parser("list", help="List enrolled templates")
    _add_common_args(list_cmd)
    list_cmd.add_argument("--profile", default=None)
    list_cmd.set_defaults(func=_cmd_list)

    delete = subparsers.add_parser("delete", help="Securely delete an enrolled template")
    _add_common_args(delete)
    delete.add_argument("--kind", choices=["face", "voice"], required=True)
    delete.add_argument("--profile", default="owner")
    delete.set_defaults(func=_cmd_delete)

    calibrate = subparsers.add_parser("calibrate", help="Calibrate thresholds for a profile")
    _add_common_args(calibrate)
    calibrate.add_argument("--kind", choices=["face", "voice"], default="face")
    calibrate.add_argument("--profile", default="owner")
    calibrate.add_argument("--impostors", default=None, help="Directory of impostor samples")
    calibrate.add_argument("--target-far", type=float, default=0.01)
    calibrate.add_argument("--target-frr", type=float, default=0.05)
    calibrate.set_defaults(func=_cmd_calibrate)

    bench = subparsers.add_parser(
        "bench", help="Measure latency/memory against configured providers"
    )
    _add_common_args(bench)
    bench.add_argument("--kind", choices=["face", "voice"], default="face")
    bench.add_argument("--profile", default="owner")
    bench.add_argument(
        "--sample", default=None, help="Sample image (face) or .wav file (voice) to verify repeatedly"
    )
    bench.add_argument("--iterations", type=int, default=20)
    bench.set_defaults(func=_cmd_bench)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BiometricsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
