"""Continuous monitor over the configured cameras (SPEC.md ampliación,
requisitos 21 and 39).

One `SourceWorker` per enabled camera samples it at its own cadence
(`sample_fps`) and hands every frame to `PresenceService.observe`. Two rules
shape it:

* **Perception never dies.** A camera that fails is marked DOWN and retried
  with exponential backoff; a frame that fails processing is logged and
  skipped. Neither ends the thread, and neither reaches the other cameras.
* **One writer.** `PresenceService` and `PresenceStore` are single writer: one
  SQLite connection, one transaction flag and one queue of pending visit
  events. Every call into the service therefore goes through `service_lock`,
  which the runner shares with the periodic jobs and the review page.
  Capturing a frame, the slow part that waits on hardware, happens outside the
  lock. Cameras overlap on I/O but take turns on inference.

Each worker's cycle is `step()`, a plain method, so the logic is testable
without threads; the thread is only a loop around it. The monitor does not own
the frame sources: whoever built them closes them after `stop()`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from time import monotonic
from typing import Protocol

from janus_presence.camera_sources import enabled_cameras
from janus_presence.frame_source import FrameSource
from janus_presence.models import SourceConfig
from janus_presence.store import utcnow

__all__ = [
    "DEFAULT_SAMPLE_FPS",
    "BackoffPolicy",
    "FrameObserver",
    "ServiceLock",
    "SourceHealth",
    "SourceMonitor",
    "SourceState",
    "SourceWorker",
]

_log = logging.getLogger(__name__)

# SPEC.md Open Questions: sampling cadence per source type is still to be
# measured. Four frames per second is the starting point the runner config
# example already uses.
DEFAULT_SAMPLE_FPS = 4.0
_STOP_TIMEOUT_S = 5.0
# A processing error repeats on every frame until whatever caused it is fixed,
# so only the first and every hundredth are logged.
_PROCESSING_LOG_EVERY = 100

ServiceLock = AbstractContextManager[object]


class FrameObserver(Protocol):
    """The part of PresenceService the monitor uses."""

    def observe(self, source_id: str, frame: bytes) -> object: ...


class SourceState(StrEnum):
    STARTING = "starting"
    UP = "up"
    DOWN = "down"
    STOPPED = "stopped"


@dataclass(frozen=True)
class SourceHealth:
    """Health of one source, as the runner reports it (requisito 39).

    DOWN means capture is failing. Frames that fail processing do not make a
    source DOWN; they are counted in `processing_errors`."""

    source_id: str
    state: SourceState = SourceState.STARTING
    last_frame_at: datetime | None = None
    consecutive_failures: int = 0
    processing_errors: int = 0
    last_error: str | None = None
    retry_in_s: float | None = None


@dataclass(frozen=True)
class BackoffPolicy:
    initial_s: float = 1.0
    factor: float = 2.0
    max_s: float = 30.0

    def __post_init__(self) -> None:
        if self.initial_s <= 0 or self.factor < 1 or self.max_s < self.initial_s:
            raise ValueError("backoff needs initial_s > 0, factor >= 1 and max_s >= initial_s")

    def delay(self, failures: int) -> float:
        """Seconds to wait after the `failures`th consecutive failure (1 based)."""
        try:
            delay = self.initial_s * self.factor ** (failures - 1)
        except OverflowError:
            # A camera unplugged overnight racks up thousands of failures.
            return self.max_s
        return min(self.max_s, delay)


class SourceWorker:
    """Samples one camera. `step()` is one capture and observe cycle and
    returns how long to wait before the next one."""

    def __init__(
        self,
        config: SourceConfig,
        source: FrameSource,
        observer: FrameObserver,
        service_lock: ServiceLock,
        backoff: BackoffPolicy,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._config = config
        self._source = source
        self._observer = observer
        self._service_lock = service_lock
        self._backoff = backoff
        self._clock = clock
        self._interval_s = 1.0 / (config.sample_fps or DEFAULT_SAMPLE_FPS)
        self._health = SourceHealth(config.source_id)
        self._health_lock = threading.Lock()
        # The newest captured frame, kept only for the live view on the review
        # page. Replaced on every capture, never written to disk.
        self._latest_frame: bytes | None = None
        self._latest_at = float("-inf")
        self._frame_lock = threading.Lock()
        self._consecutive_processing_errors = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def source_id(self) -> str:
        return self._config.source_id

    @property
    def health(self) -> SourceHealth:
        with self._health_lock:
            return self._health

    @property
    def latest_frame(self) -> bytes | None:
        return self._latest_frame

    def fresh_frame(self, max_age_s: float) -> bytes | None:
        """A frame no older than `max_age_s` for the live view. When the newest one
        is older, the camera is read again, so a viewer sees motion at a higher
        rate than the detector samples at. Several viewers share one read per
        interval. Never touches the source while it is down (the backoff owns
        retrying) and falls back to the last frame if a read fails."""
        with self._frame_lock:
            latest = self._latest_frame
            if latest is not None and self._clock() - self._latest_at <= max_age_s:
                return latest
            if self.health.state != SourceState.UP:
                return latest
            try:
                frame = self._source.capture_frame(self._config.source_id)
            except Exception as exc:
                _log.debug("source_id=%s live read failed: %s", self._config.source_id, exc)
                return latest
            self._remember(frame)
            return frame

    def _remember(self, frame: bytes) -> None:
        self._latest_frame = frame
        self._latest_at = self._clock()

    def step(self) -> float:
        started = self._clock()
        frame = self._capture()
        if frame is None:
            return self.health.retry_in_s or 0.0
        self._observe(frame)
        return max(0.0, self._interval_s - (self._clock() - started))

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"source-{self._config.source_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout_s: float = _STOP_TIMEOUT_S) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.step())
        self._set_health(state=SourceState.STOPPED, retry_in_s=None)

    def _capture(self) -> bytes | None:
        try:
            frame = self._source.capture_frame(self._config.source_id)
        except Exception as exc:
            # The source is hardware or a network stream. Whatever it raised,
            # the answer is the same: mark it down and retry after the backoff.
            self._record_failure(exc)
            return None
        self._record_frame()
        self._remember(frame)
        return frame

    def _observe(self, frame: bytes) -> None:
        try:
            with self._service_lock:
                self._observer.observe(self._config.source_id, frame)
        except Exception as exc:
            # One bad frame must not end the loop, so detection and database
            # errors are contained here.
            self._record_processing_error(exc)
            return
        self._consecutive_processing_errors = 0

    def _record_failure(self, exc: Exception) -> None:
        failures = self.health.consecutive_failures + 1
        delay = self._backoff.delay(failures)
        log = _log.warning if failures == 1 else _log.debug
        log(
            "source_id=%s capture failed (attempt %d): %s; retrying in %.1fs",
            self._config.source_id,
            failures,
            exc,
            delay,
        )
        self._set_health(
            state=SourceState.DOWN,
            consecutive_failures=failures,
            last_error=str(exc),
            retry_in_s=delay,
        )

    def _record_frame(self) -> None:
        previous = self.health
        if previous.state == SourceState.DOWN:
            _log.info(
                "source_id=%s recovered after %d failed attempts",
                self._config.source_id,
                previous.consecutive_failures,
            )
        self._set_health(
            state=SourceState.UP,
            last_frame_at=utcnow(),
            consecutive_failures=0,
            last_error=None,
            retry_in_s=None,
        )

    def _record_processing_error(self, exc: Exception) -> None:
        self._consecutive_processing_errors += 1
        count = self._consecutive_processing_errors
        if count == 1 or count % _PROCESSING_LOG_EVERY == 0:
            _log.warning(
                "source_id=%s: frame not processed (%d in a row): %s",
                self._config.source_id,
                count,
                exc,
                exc_info=count == 1,
            )
        self._set_health(processing_errors=self.health.processing_errors + 1)

    def _set_health(self, **changes: object) -> None:
        with self._health_lock:
            self._health = replace(self._health, **changes)


class SourceMonitor:
    """Runs one worker per enabled camera. Microphones are not sampled here:
    audio has its own source and lands with the voice activation block."""

    def __init__(
        self,
        configs: Iterable[SourceConfig],
        sources: Mapping[str, FrameSource],
        observer: FrameObserver,
        service_lock: ServiceLock,
        backoff: BackoffPolicy | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        cameras = enabled_cameras(configs)
        missing = [config.source_id for config in cameras if config.source_id not in sources]
        if missing:
            raise ValueError(f"no frame source for: {', '.join(missing)}")
        policy = backoff or BackoffPolicy()
        self._workers = [
            SourceWorker(config, sources[config.source_id], observer, service_lock, policy, clock)
            for config in cameras
        ]

    def start(self) -> None:
        for worker in self._workers:
            worker.start()

    def stop(self) -> None:
        for worker in self._workers:
            worker.stop()

    def health(self) -> list[SourceHealth]:
        return [worker.health for worker in self._workers]

    def fresh_frame(self, source_id: str, max_age_s: float) -> bytes | None:
        """A recent frame of one camera for the live view, or None if the source
        is unknown or has produced nothing yet."""
        for worker in self._workers:
            if worker.source_id == source_id:
                return worker.fresh_frame(max_age_s)
        return None

    def __enter__(self) -> SourceMonitor:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
