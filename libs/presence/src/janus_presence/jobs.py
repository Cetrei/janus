"""Periodic jobs of the runner (SPEC.md ampliación, requisitos 12, 17, 30, 34).

Some duties depend on the passage of time rather than on a new frame arriving:
closing visits, closing clips, expiring snapshots, trimming disk use and
forgetting identities nobody confirmed. `PresenceService` implements each of
them and says in its docstrings that a runner calls them periodically. This
module is that caller.

`JobRunner.run_due()` is the whole scheduling logic and takes an injectable
clock, so it is testable without threads; the background thread is a loop
around it. A job that raises is logged and scheduled again after its normal
interval, so one broken duty never stops the others or spins in a tight loop.
Every job runs under the same `service_lock` the monitor uses, because the
service is single writer (see monitor.py).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from janus_presence.monitor import ServiceLock

if TYPE_CHECKING:
    from janus_presence.models import PresenceConfig
    from janus_presence.service import PresenceService

__all__ = ["JobRunner", "PeriodicJob", "default_jobs"]

_log = logging.getLogger(__name__)

_TICK_S = 1.0
_STOP_TIMEOUT_S = 5.0

# Visits close within `visit_gap_s` plus one check, so the check follows the gap
# but stays between one and five seconds.
_VISIT_CHECK_MAX_S = 5.0
_VISIT_CHECK_GAP_DIVISOR = 3.0
_VISIT_CHECK_MIN_S = 1.0
# A clip is closed as soon as its end time passes.
_CLIP_CLOSE_INTERVAL_S = 1.0
# Snapshots expire on a scale of hours (unknown_snapshot_retention_s), so a
# minute of lag is invisible. Retention only shrinks after a write, but clips
# grow after the trim that precedes them, hence the periodic check.
_SNAPSHOT_EXPIRY_INTERVAL_S = 60.0
_RETENTION_INTERVAL_S = 300.0
# forget_after_days is counted in days.
_FORGET_INTERVAL_S = 3600.0


@dataclass(frozen=True)
class PeriodicJob:
    name: str
    interval_s: float
    action: Callable[[], object]

    def __post_init__(self) -> None:
        if self.interval_s <= 0:
            raise ValueError(f"job '{self.name}': interval_s must be greater than zero")


class JobRunner:
    """Runs each job when its interval has elapsed. Every job is due on the
    first pass, which also catches up on whatever came due while the runner
    was stopped (all the jobs are idempotent)."""

    def __init__(
        self,
        jobs: Iterable[PeriodicJob],
        service_lock: ServiceLock,
        clock: Callable[[], float] = monotonic,
        tick_s: float = _TICK_S,
    ) -> None:
        self._jobs = list(jobs)
        names = [job.name for job in self._jobs]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicated job name in: {', '.join(names)}")
        self._service_lock = service_lock
        self._clock = clock
        self._tick_s = tick_s
        start = clock()
        self._next_run = {job.name: start for job in self._jobs}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_due(self) -> list[str]:
        """Runs every job that is due and returns the names it attempted."""
        now = self._clock()
        attempted: list[str] = []
        for job in self._jobs:
            if self._next_run[job.name] > now:
                continue
            self._next_run[job.name] = now + job.interval_s
            self._run(job)
            attempted.append(job.name)
        return attempted

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="presence-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = _STOP_TIMEOUT_S) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_due()
            self._stop.wait(self._tick_s)

    def _run(self, job: PeriodicJob) -> None:
        try:
            with self._service_lock:
                result = job.action()
        except Exception:
            _log.exception("job %s failed; it will run again in %.0fs", job.name, job.interval_s)
            return
        if isinstance(result, list) and result:
            _log.info("job %s handled %d item(s)", job.name, len(result))


def _visit_check_interval(visit_gap_s: float) -> float:
    gap_share = visit_gap_s / _VISIT_CHECK_GAP_DIVISOR
    return max(_VISIT_CHECK_MIN_S, min(_VISIT_CHECK_MAX_S, gap_share))


def default_jobs(service: PresenceService, config: PresenceConfig) -> list[PeriodicJob]:
    """The runner's periodic duties, in the order they matter: visits and
    clips first, since consumers wait on those events."""
    visit_check_s = _visit_check_interval(config.visit_gap_s)
    return [
        PeriodicJob("close_stale_visits", visit_check_s, service.close_stale_visits),
        PeriodicJob("close_due_clips", _CLIP_CLOSE_INTERVAL_S, service.close_due_clips),
        PeriodicJob("expire_snapshots", _SNAPSHOT_EXPIRY_INTERVAL_S, service.expire_snapshots),
        PeriodicJob("enforce_retention", _RETENTION_INTERVAL_S, service.enforce_retention),
        PeriodicJob("forget_stale_unknowns", _FORGET_INTERVAL_S, service.forget_stale_unknowns),
    ]
