"""The autonomous runner (SPEC.md ampliación, requisito 39): `python -m
janus_presence run --config presence.toml`.

`build_runner` wires the parts the other modules provide: store, index, clip
recorder and service (the perception core), a `SourceMonitor` per enabled
camera, the periodic `JobRunner`, the JSONL event log and the local review
page. `PresenceRunner` only owns their order:

* **Start**: jobs first (they also catch up on whatever came due while the
  runner was off), then the cameras, then the review page, so nothing serves
  requests before the system behind it is running.
* **Stop**: the reverse for the inputs (review page, cameras, jobs), then the
  camera devices, then the service (recorder, index, database), and the event
  log last so the final events still get written. Each step runs even if the
  one before it failed; a stuck step must not keep the database open.

Two settings the file may carry are accepted but not acted on yet, and the
runner says so at startup instead of ignoring them silently: microphones and
voice thresholds (audio sources and wake word activation land with the voice
activation block).
"""

from __future__ import annotations

import logging
import secrets
import signal
import threading
from collections.abc import Callable
from pathlib import Path

from janus_platform.paths import PrivacyStatus, privacy_status, write_private

from janus_presence.camera_sources import PersistentCameraSource, enabled_cameras
from janus_presence.clip_recorder import ClipRecorder
from janus_presence.errors import PresenceError
from janus_presence.event_log import JsonlEventLog, attach_event_log
from janus_presence.ha_sink import HomeAssistantSink, load_token
from janus_presence.index import PresenceIndex
from janus_presence.jobs import JobRunner, default_jobs
from janus_presence.models import PresenceConfig, SourceConfig, SourceKind
from janus_presence.monitor import DEFAULT_SAMPLE_FPS, ServiceLock, SourceMonitor
from janus_presence.review_auth import load_or_create_token
from janus_presence.review_backend import ServiceReviewBackend
from janus_presence.review_server import ReviewServer
from janus_presence.runner_config import RunnerConfig
from janus_presence.service import THRESHOLDS_SETTING, PresenceService
from janus_presence.store import PresenceStore

__all__ = ["PresenceRunner", "build_runner", "run_until_signal"]

_log = logging.getLogger(__name__)

_KEY_FILE_NAME = "presence.key"
_KEY_BYTES = 32  # AES-256
_WAIT_SLICE_S = 0.5


def _load_or_create_key(presence_dir: Path) -> bytes:
    """The AES key that encrypts snapshots and samples. Created on first run,
    private to the user. A missing key next to existing data is an error, not
    a reason to make a new key: that would leave every stored sample
    unreadable and the failure would only show up later, frame by frame."""
    path = presence_dir / _KEY_FILE_NAME
    if not path.exists():
        if (presence_dir / "presence.db").exists():
            raise PresenceError(
                f"Presence data exists in {presence_dir} but its key {path} is missing. "
                "Restore the key; a new one could not decrypt the stored samples."
            )
        key = secrets.token_bytes(_KEY_BYTES)
        write_private(path, key)
        _log.info("generated a new sample encryption key at %s", path)
        return key
    if privacy_status(path) == PrivacyStatus.OPEN:
        raise PresenceError(
            f"The sample key {path} is readable by other users. Restrict it to your user "
            "(chmod 600) and start again."
        )
    key = path.read_bytes()
    if len(key) != _KEY_BYTES:
        raise PresenceError(f"The sample key {path} is {len(key)} bytes, expected {_KEY_BYTES}")
    return key


def _recorder_fps(cameras: list[SourceConfig]) -> float:
    """ClipRecorder has one frame rate for every camera, and a clip plays at
    real time only if the camera is observed at that rate (see its module
    docstring). With cameras at different rates some clips will play faster
    or slower than real time; the highest rate is used and the mismatch is
    logged."""
    rates = {camera.sample_fps or DEFAULT_SAMPLE_FPS for camera in cameras}
    if len(rates) > 1:
        _log.warning(
            "cameras sample at different rates %s; clips are recorded at %s fps, so clips "
            "from slower cameras will play faster than real time",
            sorted(rates),
            max(rates),
        )
    return max(rates, default=DEFAULT_SAMPLE_FPS)


def _warn_about_unwired(config: PresenceConfig) -> None:
    microphones = [s.source_id for s in config.sources if s.kind == SourceKind.MICROPHONE]
    if microphones:
        _log.warning(
            "microphone sources %s are configured but audio is not wired into the runner yet; "
            "they are ignored",
            microphones,
        )
    if config.voice_match_threshold is not None:
        _log.warning("voice thresholds are set but voice matching is not wired into the runner")
    if not enabled_cameras(config.sources):
        _log.warning("no camera is enabled, so nothing will be observed")


def _effective_thresholds(store: PresenceStore, presence: PresenceConfig) -> tuple[float, float]:
    """The face thresholds to start with. What the owner saved from the review
    page wins over presence.toml, which stays the starting point and the
    fallback when nothing valid was saved."""
    saved = store.get_setting(THRESHOLDS_SETTING)
    valid = (
        isinstance(saved, list)
        and len(saved) == 2
        and all(isinstance(value, int | float) for value in saved)
        and 0 < saved[0] < saved[1]
    )
    if not valid:
        return presence.match_threshold, presence.match_threshold_ambiguous
    _log.info("using face thresholds saved from the review page: %s", saved)
    return float(saved[0]), float(saved[1])


def _build_service(
    config: RunnerConfig,
    presence: PresenceConfig,
    store: PresenceStore,
    frame_sources: dict[str, PersistentCameraSource],
) -> PresenceService:
    import janus_biometrics
    from janus_biometrics import ModelCache

    models_yaml = Path(janus_biometrics.__file__).parent / "models.yaml"
    presence_dir = config.state_dir / "presence"
    recorder = ClipRecorder(
        presence_dir / "clips",
        preroll_s=presence.clip_preroll_s,
        fps=_recorder_fps(enabled_cameras(presence.sources)),
    )
    match_threshold, match_threshold_ambiguous = _effective_thresholds(store, presence)
    return PresenceService(
        store=store,
        index=PresenceIndex(),
        model_cache=ModelCache(models_yaml, config.state_dir / "models"),
        frame_sources=frame_sources,  # type: ignore[arg-type]
        match_threshold=match_threshold,
        match_threshold_ambiguous=match_threshold_ambiguous,
        clip_duration_s=presence.clip_duration_s,
        clips_root=presence_dir / "clips",
        clips_max_total_mb=presence.clips_max_total_mb,
        unknown_snapshot_retention_s=presence.unknown_snapshot_retention_s,
        snapshots_root=presence_dir / "snapshots",
        established_min_samples=presence.established_min_samples,
        provisional_confidence_cap=presence.provisional_confidence_cap,
        visit_gap_s=presence.visit_gap_s,
        forget_after_days=presence.forget_after_days,
        max_samples_per_person=presence.max_samples_per_person,
        clip_recorder=recorder,
    )


def _build_review(
    config: RunnerConfig,
    service: PresenceService,
    monitor: SourceMonitor,
    service_lock: ServiceLock,
    event_log: JsonlEventLog,
) -> ReviewServer | None:
    if not config.review.enabled:
        return None
    token = load_or_create_token(config.review_token_path())
    backend = ServiceReviewBackend(service, monitor, service_lock)
    return ReviewServer(
        backend, token, config.review.host, config.review.port, audit=event_log.write
    )


class PresenceRunner:
    def __init__(
        self,
        service: PresenceService,
        monitor: SourceMonitor,
        jobs: JobRunner,
        frame_sources: PersistentCameraSource,
        event_log: JsonlEventLog,
        review: ReviewServer | None = None,
        ha_sink: HomeAssistantSink | None = None,
    ) -> None:
        self._service = service
        self._monitor = monitor
        self._jobs = jobs
        self._frame_sources = frame_sources
        self._event_log = event_log
        self._review = review
        self._ha_sink = ha_sink

    @property
    def review_url(self) -> str | None:
        return self._review.url if self._review is not None else None

    def start(self) -> None:
        if self._ha_sink is not None:
            self._ha_sink.start()
        self._jobs.start()
        self._monitor.start()
        if self._review is not None:
            self._review.start()

    def stop(self) -> None:
        """Safe to call on a runner that never started, and more than once."""
        steps: list[Callable[[], None]] = [
            self._review.stop if self._review is not None else _nothing,
            self._monitor.stop,
            self._jobs.stop,
            self._ha_sink.stop if self._ha_sink is not None else _nothing,
            self._frame_sources.close,
            self._service.close,
            self._event_log.close,
        ]
        _run_all(steps)


def _nothing() -> None:
    return None


def _run_all(steps: list[Callable[[], None]]) -> None:
    for step in steps:
        try:
            step()
        except Exception:
            _log.exception("shutdown step %s failed; continuing", getattr(step, "__name__", step))


def _build_home_assistant(
    config: RunnerConfig, service: PresenceService
) -> HomeAssistantSink | None:
    """The sink that tells Home Assistant about visits, when the config has a
    [home_assistant] section. A missing or open token file fails the start."""
    section = config.home_assistant
    if section is None:
        return None
    sink = HomeAssistantSink(
        section.url,
        load_token(section.token_file),
        timeout_s=section.timeout_s,
        max_queue=section.queue_size,
    )
    sink.attach(service)
    return sink


def build_runner(config: RunnerConfig) -> PresenceRunner:
    """Builds every part from the config. Anything that fails after the
    database is open closes what was opened before raising."""
    presence = config.presence_config()
    _warn_about_unwired(presence)
    presence_dir = config.state_dir / "presence"
    presence_dir.mkdir(parents=True, exist_ok=True)
    key = _load_or_create_key(presence_dir)
    cameras = enabled_cameras(presence.sources)
    camera_source = PersistentCameraSource(cameras)
    frame_sources = {camera.source_id: camera_source for camera in cameras}

    store = PresenceStore(config.state_dir, key)
    try:
        service = _build_service(config, presence, store, frame_sources)
    except BaseException:
        store.close()
        raise
    event_log = JsonlEventLog(config.event_log_path(), config.events.max_bytes)
    try:
        for source in presence.sources:
            store.upsert_source(source)
        attach_event_log(service, event_log, include_person_seen=config.events.log_person_seen)
        lock = threading.RLock()
        monitor = SourceMonitor(presence.sources, frame_sources, service, lock)
        jobs = JobRunner(default_jobs(service, presence), lock)
        review = _build_review(config, service, monitor, lock, event_log)
        ha_sink = _build_home_assistant(config, service)
    except BaseException:
        _run_all([camera_source.close, service.close, event_log.close])
        raise
    return PresenceRunner(service, monitor, jobs, camera_source, event_log, review, ha_sink)


def _install_stop_handlers(stop: threading.Event) -> dict[int, object]:
    if threading.current_thread() is not threading.main_thread():
        return {}
    previous: dict[int, object] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, lambda *_: stop.set())
    return previous


def run_until_signal(runner: PresenceRunner, stop: threading.Event | None = None) -> None:
    """Runs until Ctrl+C, SIGTERM or `stop` is set, then shuts down in order.
    Waits in short slices because a blocking wait is not interrupted by Ctrl+C
    on Windows."""
    stop = stop or threading.Event()
    previous = _install_stop_handlers(stop)
    try:
        runner.start()
        while not stop.wait(_WAIT_SLICE_S):
            pass
    finally:
        runner.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)  # type: ignore[arg-type]
