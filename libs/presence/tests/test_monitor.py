"""Source monitor (requisitos 21, 39): sampling cadence, health, backoff and
the single writer lock. Cycles are driven through `step()` with a fake clock;
one test runs the real threads."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from conftest import CountingLock, FakeClock

from janus_presence.errors import PresenceUnavailableError
from janus_presence.models import SourceConfig, SourceKind, SourceLocation
from janus_presence.monitor import (
    DEFAULT_SAMPLE_FPS,
    BackoffPolicy,
    SourceMonitor,
    SourceState,
    SourceWorker,
)

SOURCE = "cuarto"
BACKOFF = BackoffPolicy(initial_s=1.0, factor=2.0, max_s=8.0)


def make_config(
    source_id: str = SOURCE,
    kind: SourceKind = SourceKind.CAMERA,
    enabled: bool = True,
    sample_fps: float | None = 4.0,
) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        kind=kind,
        source=SourceLocation.LOCAL,
        device="0",
        label=source_id,
        enabled=enabled,
        sample_fps=sample_fps,
    )


class ScriptedSource:
    """Plays back a script: bytes are frames, exceptions are raised. Records
    whether the service lock was held while capturing."""

    def __init__(self, *results: object, lock: CountingLock | None = None) -> None:
        self.results = list(results)
        self.lock = lock
        self.held_while_capturing: list[bool] = []

    def capture_frame(self, camera_id: str) -> bytes:
        if self.lock is not None:
            self.held_while_capturing.append(self.lock.active)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[return-value]


class EndlessSource:
    def capture_frame(self, camera_id: str) -> bytes:
        return b"frame"


class RecordingObserver:
    def __init__(
        self,
        clock: FakeClock | None = None,
        cost_s: float = 0.0,
        lock: CountingLock | None = None,
        on_call: Callable[[int], None] | None = None,
    ) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.error: Exception | None = None
        self.held: list[bool] = []
        self._clock = clock
        self._cost_s = cost_s
        self._lock = lock
        self._on_call = on_call

    def observe(self, source_id: str, frame: bytes) -> None:
        self.calls.append((source_id, frame))
        if self._lock is not None:
            self.held.append(self._lock.active)
        if self._clock is not None:
            self._clock.now += self._cost_s
        if self._on_call is not None:
            self._on_call(len(self.calls))
        if self.error is not None:
            raise self.error


def make_worker(
    source: object,
    observer: RecordingObserver | None = None,
    clock: FakeClock | None = None,
    lock: CountingLock | None = None,
    config: SourceConfig | None = None,
) -> SourceWorker:
    return SourceWorker(
        config or make_config(),
        source,  # type: ignore[arg-type]
        observer or RecordingObserver(),
        lock or CountingLock(),
        BACKOFF,
        clock or FakeClock(),
    )


def unplugged() -> PresenceUnavailableError:
    return PresenceUnavailableError(f"camera:{SOURCE}", "unplugged")


class TestSourceWorkerCadence:
    def test_a_frame_is_observed_and_the_source_is_up(self):
        observer = RecordingObserver()
        worker = make_worker(ScriptedSource(b"f1"), observer)

        worker.step()

        assert observer.calls == [(SOURCE, b"f1")]
        assert worker.health.state == SourceState.UP
        assert worker.health.last_frame_at is not None
        assert worker.health.consecutive_failures == 0

    def test_it_waits_out_the_rest_of_the_sampling_interval(self):
        clock = FakeClock()
        observer = RecordingObserver(clock=clock, cost_s=0.1)
        worker = make_worker(ScriptedSource(b"f"), observer, clock=clock)

        assert worker.step() == pytest.approx(0.15)

    def test_a_slow_frame_leaves_no_wait_at_all(self):
        clock = FakeClock()
        observer = RecordingObserver(clock=clock, cost_s=0.5)
        worker = make_worker(ScriptedSource(b"f"), observer, clock=clock)

        assert worker.step() == 0.0

    def test_a_source_without_a_rate_uses_the_default(self):
        worker = make_worker(ScriptedSource(b"f"), config=make_config(sample_fps=None))

        assert worker.step() == pytest.approx(1.0 / DEFAULT_SAMPLE_FPS)


class TestSourceWorkerFailures:
    def test_a_failed_capture_marks_the_source_down_and_backs_off(self):
        observer = RecordingObserver()
        worker = make_worker(ScriptedSource(unplugged()), observer)

        delay = worker.step()

        health = worker.health
        assert delay == 1.0
        assert observer.calls == []
        assert health.state == SourceState.DOWN
        assert health.consecutive_failures == 1
        assert "unplugged" in (health.last_error or "")
        assert health.retry_in_s == 1.0

    def test_backoff_grows_with_each_consecutive_failure_up_to_the_cap(self):
        worker = make_worker(ScriptedSource(*[unplugged() for _ in range(5)]))

        assert [worker.step() for _ in range(5)] == [1.0, 2.0, 4.0, 8.0, 8.0]

    def test_a_good_frame_after_failures_brings_the_source_back(self):
        worker = make_worker(ScriptedSource(unplugged(), b"f"))

        worker.step()
        worker.step()

        health = worker.health
        assert health.state == SourceState.UP
        assert health.consecutive_failures == 0
        assert health.last_error is None
        assert health.retry_in_s is None

    def test_an_unexpected_error_from_the_source_is_a_failure_not_a_crash(self):
        worker = make_worker(ScriptedSource(RuntimeError("driver bug")))

        assert worker.step() == 1.0
        assert worker.health.state == SourceState.DOWN

    def test_a_frame_that_fails_processing_does_not_take_the_source_down(self):
        observer = RecordingObserver()
        observer.error = RuntimeError("model blew up")
        worker = make_worker(ScriptedSource(b"f1", b"f2"), observer)

        worker.step()
        worker.step()

        assert worker.health.state == SourceState.UP
        assert worker.health.processing_errors == 2
        assert len(observer.calls) == 2


class TestServiceLock:
    def test_observing_holds_the_lock_and_capturing_does_not(self):
        lock = CountingLock()
        source = ScriptedSource(b"f", lock=lock)
        observer = RecordingObserver(lock=lock)
        worker = make_worker(source, observer, lock=lock)

        worker.step()

        assert source.held_while_capturing == [False]
        assert observer.held == [True]
        assert lock.entries == 1
        assert not lock.active


class TestBackoffPolicy:
    def test_a_huge_failure_count_stays_at_the_cap(self):
        assert BackoffPolicy(initial_s=1.0, factor=2.0, max_s=30.0).delay(5000) == 30.0

    @pytest.mark.parametrize(
        "kwargs",
        [{"initial_s": 0}, {"factor": 0.5}, {"initial_s": 10.0, "max_s": 5.0}],
    )
    def test_an_invalid_policy_is_refused(self, kwargs):
        with pytest.raises(ValueError, match="backoff"):
            BackoffPolicy(**kwargs)


class TestSourceMonitor:
    def test_only_enabled_cameras_get_a_worker(self):
        configs = [
            make_config("a"),
            make_config("b", enabled=False),
            make_config("mic", kind=SourceKind.MICROPHONE),
        ]

        monitor = SourceMonitor(
            configs, {"a": EndlessSource()}, RecordingObserver(), CountingLock()
        )

        assert [health.source_id for health in monitor.health()] == ["a"]

    def test_a_camera_without_a_frame_source_is_refused(self):
        with pytest.raises(ValueError, match=SOURCE):
            SourceMonitor([make_config()], {}, RecordingObserver(), CountingLock())

    def test_the_threads_sample_until_stopped(self):
        enough = threading.Event()
        observer = RecordingObserver(on_call=lambda count: enough.set() if count >= 3 else None)
        monitor = SourceMonitor(
            [make_config(sample_fps=500.0)],
            {SOURCE: EndlessSource()},
            observer,
            threading.RLock(),
        )

        monitor.start()
        try:
            assert enough.wait(timeout=5.0)
        finally:
            monitor.stop()

        assert monitor.health()[0].state == SourceState.STOPPED
