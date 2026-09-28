"""Manual, LIVE end-to-end check of libs/presence: real camera + real
YuNet/SFace models + the real compiled hnsw-c index. NOT a pytest file: it
needs a person in front of a camera, same as
libs/biometrics/tests/manual_e2e_check.py, whose camera and model plumbing
it reuses. No photos are needed: you are the test subject.

What it walks through, on one persistent database (tests/.manual_e2e_check/):

    observe      capture a frame, run it through PresenceService.observe
    status       people, embeddings, pending evidence, open visits
    name         UNKNOWN -> PROVISIONAL
    review       list PENDING evidence, confirm/reject it, reach ESTABLISHED
    calibrate    measure REAL distances between your own frames (and against
                 someone else's) so match_threshold is chosen from data, not
                 guessed: presence has no default for it on purpose
    run          guided script of all of the above, in order
    reset        securely delete this test database

Setup, from libs/presence/ (biometrics' `face-gui` extra brings opencv with
GUI + V4L2; the `face` extra is headless and cannot open a window):

    uv sync --extra face-gui
    (if presence does not expose that extra, run it from libs/biometrics/ with
     `uv run --directory ../presence ...` or install opencv-python there)

Usage:

    uv run python tests/manual_e2e_check.py calibrate     # do this first
    uv run python tests/manual_e2e_check.py run --match 0.6 --ambiguous 1.2
    uv run python tests/manual_e2e_check.py status        # in a NEW terminal: does it remember?

The whole point of `status` in a fresh process is requisito 7: the index is
in memory only, so a new process must rebuild it from the encrypted samples
and still recognise you.

Decision thresholds are passed on the command line and are printed with
every result. Distances are squared Euclidean between SFace embeddings.
"""

from __future__ import annotations

import argparse
import itertools
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

# Reuse biometrics' manual camera helpers (camera opening, live preview with
# detection overlay, model cache). Importing it puts biometrics' src/ on
# sys.path and exits with an install hint if opencv is missing.
_BIOMETRICS_TESTS = Path(__file__).resolve().parents[2] / "biometrics" / "tests"
sys.path.insert(0, str(_BIOMETRICS_TESTS))
import manual_camera_check as cam  # noqa: E402, I001
import cv2  # noqa: E402

from janus_biometrics import _face_pipeline as pipeline  # noqa: E402
from janus_biometrics import detect_and_embed_faces  # noqa: E402
from janus_platform.paths import write_private  # noqa: E402

from janus_presence.errors import PresenceError  # noqa: E402
from janus_presence.index import PresenceIndex  # noqa: E402
from janus_presence.models import EvidenceStatus  # noqa: E402
from janus_presence.service import PresenceService  # noqa: E402
from janus_presence.store import PresenceStore  # noqa: E402

_STATE_DIR = Path(__file__).parent / ".manual_e2e_check"
_KEY_FILE = _STATE_DIR / "presence.key"
_CAMERA_ID = "e2e-camera"
_KEY_SIZE_BYTES = 32  # AES-256
_CALIBRATION_SHOTS = 6
_DEFAULT_MATCH = 0.6
_DEFAULT_AMBIGUOUS = 1.2


# --------------------------------------------------------------- plumbing


def _ensure_key() -> bytes:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not _KEY_FILE.exists():
        write_private(_KEY_FILE, secrets.token_bytes(_KEY_SIZE_BYTES))
        print(f"Generated a new sample key at {_KEY_FILE}")
    return _KEY_FILE.read_bytes()


def _build_service(args: argparse.Namespace) -> PresenceService:
    """A fresh PresenceService over the persistent test database. A new call
    is a new 'process' as far as the in-memory index goes: it is rebuilt
    from the encrypted samples, which is exactly what is being tested."""
    store = PresenceStore(_STATE_DIR, _ensure_key())
    return PresenceService(
        store=store,
        index=PresenceIndex(),
        model_cache=cam._make_cache(),
        frame_sources={},  # clips are only a path reference in F1, no capture needed
        match_threshold=args.match,
        match_threshold_ambiguous=args.ambiguous,
        clip_duration_s=5,
        clips_root=_STATE_DIR / "clips",
        clips_max_total_mb=64,
        unknown_snapshot_retention_s=3600,
        snapshots_root=_STATE_DIR / "snapshots",
        established_min_samples=args.established,
        visit_gap_s=args.visit_gap,
    )


def _capture(camera, detector, prompt: str) -> bytes | None:
    """One live capture through biometrics' preview. Returns PNG bytes, or
    None if the user aborted with ESC."""
    captured = cam._live_capture(camera, detector, prompt)
    return None if captured is None else captured[0]


def _open(args: argparse.Namespace):
    camera = cam._open_camera(args.camera)
    detector = cam._bootstrap_detector(cam._make_cache(), camera)
    return camera, detector


def _short(person_id: str) -> str:
    return person_id[:8]


# ------------------------------------------------------------- calibrate


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Measures real squared distances so the thresholds are chosen from
    data. Phase 1: you alone, several frames -> the SAME-person distances.
    Phase 2 (optional): someone else -> the DIFFERENT-person distances.
    match_threshold belongs above the first group and below the second."""
    cache = cam._make_cache()
    camera, detector = _open(args)
    same: list[list[float]] = []
    other: list[list[float]] = []
    try:
        print(f"\nPhase 1: {_CALIBRATION_SHOTS} frames of YOU. Change angle and expression a bit.")
        same = _collect_embeddings(camera, detector, cache, _CALIBRATION_SHOTS, "You")
        if args.with_other:
            print("\nPhase 2: hand the camera to SOMEONE ELSE, same number of frames.")
            other = _collect_embeddings(camera, detector, cache, _CALIBRATION_SHOTS, "Other person")
    finally:
        camera.close()
        cv2.destroyAllWindows()

    _report(same, other)
    return 0


def _collect_embeddings(camera, detector, cache, count: int, who: str) -> list[list[float]]:
    embeddings: list[list[float]] = []
    while len(embeddings) < count:
        image = _capture(camera, detector, f"{who}: {len(embeddings) + 1}/{count}")
        if image is None:
            raise SystemExit("Aborted by user.")
        faces = detect_and_embed_faces(image, cache)
        if len(faces) != 1:
            print(f"  need exactly one face, saw {len(faces)}. Again.")
            continue
        if not faces[0].quality_ok:
            print("  quality gate failed (too small/blurry/dark). Again.")
            continue
        embeddings.append(faces[0].embedding)
        print(f"  {who} {len(embeddings)}/{count} OK")
    return embeddings


def _squared_distance(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))


def _spread(values: list[float]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    median = ordered[len(ordered) // 2]
    return f"min={ordered[0]:.3f}  median={median:.3f}  max={ordered[-1]:.3f}"


def _report(same: list[list[float]], other: list[list[float]]) -> None:
    same_d = [_squared_distance(a, b) for a, b in itertools.combinations(same, 2)]
    print("\n--- Calibration ---")
    print(f"same person   ({len(same_d):>2} pairs): {_spread(same_d)}")
    if not other:
        print("different person: not measured (re-run with --with-other).")
        if same_d:
            print(f"\nmatch_threshold should sit ABOVE {max(same_d):.3f}.")
            print("Without a second person the upper bound is unknown: expect it well above.")
        return
    cross_d = [_squared_distance(a, b) for a in same for b in other]
    print(f"other person  ({len(cross_d):>2} pairs): {_spread(cross_d)}")
    worst_same, best_other = max(same_d), min(cross_d)
    if worst_same < best_other:
        middle = (worst_same + best_other) / 2
        print(f"\nClean separation. Suggested: --match {worst_same * 1.15:.3f} "
              f"(midpoint {middle:.3f}), --ambiguous {best_other:.3f}")
    else:
        print(
            f"\nOVERLAP: your worst frame pair ({worst_same:.3f}) is farther than the closest "
            f"stranger ({best_other:.3f}). No single threshold separates them on this data: "
            "the ambiguous zone and the decision gate matter here. Capture more/better frames."
        )


# ---------------------------------------------------------------- observe


def _observe_once(service: PresenceService, camera, detector, prompt: str) -> None:
    image = _capture(camera, detector, prompt)
    if image is None:
        raise SystemExit("Aborted by user.")
    sighting = service.observe(_CAMERA_ID, image)
    if sighting is None:
        print("  no face detected in that frame.")
        return
    person = service._store.get_person(sighting.person_id)
    assert person is not None
    print(
        f"  -> person {_short(person.person_id)}  state={person.state.value}  "
        f"label={person.label}  confidence={sighting.confidence:.3f}"
    )


def cmd_observe(args: argparse.Namespace) -> int:
    service = _build_service(args)
    camera, detector = _open(args)
    try:
        for shot in range(args.shots):
            _observe_once(service, camera, detector, f"Observe {shot + 1}/{args.shots}")
    finally:
        camera.close()
        cv2.destroyAllWindows()
        service.close()
    return 0


# ------------------------------------------------------- status / name / review


def _print_status(service: PresenceService) -> None:
    status = service.status()
    print(
        f"known={status.known_persons}  unknown={status.unknown_persons}  "
        f"embeddings_in_index={status.index_size}"
    )
    for person in service._store.all_persons():
        embeddings = len(service._store.embeddings_for_person(person.person_id))
        print(
            f"  {_short(person.person_id)}  {person.state.value:<11} label={person.label!s:<12} "
            f"role={person.role}  embeddings={embeddings}"
        )
    pending = service._store.pending_evidence()
    print(f"pending evidence: {len(pending)}   open visits: {len(service._store.open_visits())}")


def cmd_status(args: argparse.Namespace) -> int:
    service = _build_service(args)
    try:
        _print_status(service)
    finally:
        service.close()
    return 0


def cmd_name(args: argparse.Namespace) -> int:
    service = _build_service(args)
    try:
        target = _find_person(service, args.person)
        person = service.name_person(target, args.label)
        print(f"{_short(person.person_id)} is now {person.state.value} as '{person.label}'.")
    finally:
        service.close()
    return 0


def _find_person(service: PresenceService, prefix: str) -> str:
    matches = [p.person_id for p in service._store.all_persons() if p.person_id.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"'{prefix}' matches {len(matches)} people; use a longer prefix.")
    return matches[0]


def cmd_review(args: argparse.Namespace) -> int:
    """Confirms every PENDING evidence of one person. With enough of them the
    person goes PROVISIONAL -> ESTABLISHED (requisito 26)."""
    service = _build_service(args)
    try:
        person_id = _find_person(service, args.person)
        pending = [e for e in service.pending_review() if e.person_id == person_id]
        print(f"{len(pending)} pending evidence for {_short(person_id)}.")
        for evidence in pending:
            try:
                person = service.confirm_evidence(evidence.evidence_id)
            except PresenceError as exc:
                print(f"  cannot confirm: {exc}")
                return 1
            print(f"  confirmed -> state={person.state.value}")
        confirmed = service._store.count_evidence(person_id, EvidenceStatus.CONFIRMED)
        print(f"confirmed in total: {confirmed} (established at {args.established})")
    finally:
        service.close()
    return 0


# -------------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    """Guided walk: unknown -> recognised -> named -> restart -> established."""
    print("== 1/5  First sighting: you should appear as a NEW unknown.")
    service = _build_service(args)
    camera, detector = _open(args)
    try:
        _observe_once(service, camera, detector, "1/5 first sighting")
        person_id = service._store.all_persons()[-1].person_id

        print("\n== 2/5  Same person again: it must be the SAME id, not a new unknown.")
        _observe_once(service, camera, detector, "2/5 again, same person")
        _expect(len(service._store.all_persons()) == 1, "recognised as the same person")

        print("\n== 3/5  Name them: UNKNOWN -> PROVISIONAL.")
        person = service.name_person(person_id, args.label)
        _expect(person.state.value == "provisional", f"now provisional as '{args.label}'")
        _observe_once(service, camera, detector, "3/5 named, look again")
    finally:
        camera.close()
        cv2.destroyAllWindows()
        service.close()

    print("\n== 4/5  RESTART: a brand new service must rebuild the index from disk.")
    service = _build_service(args)
    camera, detector = _open(args)
    try:
        before = len(service._store.all_persons())
        _observe_once(service, camera, detector, "4/5 after restart, look again")
        _expect(len(service._store.all_persons()) == before, "still recognised after restart")

        print(f"\n== 5/5  Confirm evidence until ESTABLISHED (needs {args.established}).")
        for shot in range(args.established):
            _observe_once(service, camera, detector, f"5/5 evidence {shot + 1}/{args.established}")
        for evidence in service.pending_review():
            if evidence.person_id == person_id:
                service.confirm_evidence(evidence.evidence_id)
        final = service._store.get_person(person_id)
        assert final is not None
        _expect(final.state.value == "established", "reached ESTABLISHED")
        _print_status(service)
    finally:
        camera.close()
        cv2.destroyAllWindows()
        service.close()
    print("\nNow run `status` in a NEW terminal: it should still know you.")
    return 0


def _expect(condition: bool, description: str) -> None:
    print(f"  [{' ok ' if condition else 'FAIL'}] {description}")


# ------------------------------------------------------------------ reset


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("This deletes the whole test database and its encrypted samples. Re-run with --yes.")
        return 1
    service = _build_service(args)
    try:
        for person in service._store.all_persons():
            service.forget_person(person.person_id)
        print(f"Forgot every person ({datetime.now(UTC).isoformat()}). Key and empty db kept.")
    finally:
        service.close()
    return 0


# ------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual live end-to-end check of libs/presence")
    parser.add_argument("--camera", type=int, default=None, help="Camera index (auto if one)")
    parser.add_argument(
        "--match", type=float, default=_DEFAULT_MATCH,
        help="match_threshold (squared distance). Calibrate first; the default is a guess.",
    )
    parser.add_argument(
        "--ambiguous", type=float, default=_DEFAULT_AMBIGUOUS, help="match_threshold_ambiguous"
    )
    parser.add_argument("--established", type=int, default=3, help="confirmations to ESTABLISHED")
    parser.add_argument("--visit-gap", type=int, default=30, help="visit_gap_s")
    sub = parser.add_subparsers(dest="command", required=True)

    calibrate = sub.add_parser("calibrate", help="Measure real same/different-person distances")
    calibrate.add_argument("--with-other", action="store_true", help="also capture a 2nd person")
    observe = sub.add_parser("observe", help="Capture frames and run them through observe()")
    observe.add_argument("--shots", type=int, default=1)
    sub.add_parser("status", help="Show people, embeddings, pending evidence")
    name = sub.add_parser("name", help="Name a person (UNKNOWN -> PROVISIONAL)")
    name.add_argument("person", help="person_id prefix from `status`")
    name.add_argument("label")
    review = sub.add_parser("review", help="Confirm a person's pending evidence")
    review.add_argument("person", help="person_id prefix from `status`")
    run = sub.add_parser("run", help="Guided end-to-end walk")
    run.add_argument("--label", default="Tester")
    reset = sub.add_parser("reset", help="Forget every person in the test database")
    reset.add_argument("--yes", action="store_true")
    return parser


_COMMANDS = {
    "calibrate": cmd_calibrate,
    "observe": cmd_observe,
    "status": cmd_status,
    "name": cmd_name,
    "review": cmd_review,
    "run": cmd_run,
    "reset": cmd_reset,
}


def main() -> int:
    args = build_parser().parse_args()
    if args.match >= args.ambiguous:
        print("--ambiguous must be greater than --match.", file=sys.stderr)
        return 1
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
