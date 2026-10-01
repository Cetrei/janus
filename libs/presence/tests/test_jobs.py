"""Periodic jobs (requisitos 12, 17, 30, 34, 39): scheduling, containment of a
failing job, the single writer lock and the default duties. Scheduling is
driven through `run_due()` with a fake clock; one test runs the real thread."""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest
from conftest import CountingLock, FakeClock

from janus_presence.jobs import JobRunner, PeriodicJob, default_jobs


class Counter:
    """A job action that records how many times it ran."""

    def __init__(self, result: object = None) -> None:
        self.calls = 0
        self.result = result

    def __call__(self) -> object:
        self.calls += 1
        return self.result


def failing_action() -> object:
    raise RuntimeError("disk on fire")


def make_runner(
    *jobs: PeriodicJob,
    clock: FakeClock | None = None,
    lock: CountingLock | None = None,
) -> JobRunner:
    return JobRunner(jobs, lock or CountingLock(), clock or FakeClock())


class TestPeriodicJob:
    @pytest.mark.parametrize("interval_s", [0, -1.0])
    def test_an_interval_that_is_not_positive_is_refused(self, interval_s):
        with pytest.raises(ValueError, match="interval_s"):
            PeriodicJob("close_things", interval_s, Counter())


class TestScheduling:
    def test_every_job_is_due_on_the_first_pass(self):
        first, second = Counter(), Counter()
        runner = make_runner(PeriodicJob("first", 10.0, first), PeriodicJob("second", 60.0, second))

        attempted = runner.run_due()

        assert attempted == ["first", "second"]
        assert (first.calls, second.calls) == (1, 1)

    def test_a_job_waits_for_its_interval_before_running_again(self):
        clock = FakeClock()
        action = Counter()
        runner = make_runner(PeriodicJob("job", 10.0, action), clock=clock)

        runner.run_due()
        clock.now = 9.9
        assert runner.run_due() == []
        clock.now = 10.0
        assert runner.run_due() == ["job"]

        assert action.calls == 2

    def test_each_job_keeps_its_own_schedule(self):
        clock = FakeClock()
        fast, slow = Counter(), Counter()
        runner = make_runner(
            PeriodicJob("fast", 1.0, fast), PeriodicJob("slow", 5.0, slow), clock=clock
        )

        for second in range(6):
            clock.now = float(second)
            runner.run_due()

        assert (fast.calls, slow.calls) == (6, 2)

    def test_a_runner_started_late_does_not_run_jobs_it_has_not_reached(self):
        clock = FakeClock(now=1000.0)
        action = Counter()
        runner = make_runner(PeriodicJob("job", 10.0, action), clock=clock)

        assert runner.run_due() == ["job"]
        assert runner.run_due() == []

    def test_two_jobs_with_the_same_name_are_refused(self):
        with pytest.raises(ValueError, match="duplicated job name"):
            make_runner(PeriodicJob("same", 1.0, Counter()), PeriodicJob("same", 2.0, Counter()))


class TestFailingJob:
    def test_a_job_that_raises_does_not_stop_the_others(self):
        after = Counter()
        runner = make_runner(
            PeriodicJob("broken", 10.0, failing_action), PeriodicJob("after", 10.0, after)
        )

        attempted = runner.run_due()

        assert attempted == ["broken", "after"]
        assert after.calls == 1

    def test_a_failed_job_is_retried_after_its_normal_interval_not_at_once(self):
        clock = FakeClock()
        calls: list[float] = []

        def broken() -> object:
            calls.append(clock.now)
            raise RuntimeError("still broken")

        runner = make_runner(PeriodicJob("broken", 10.0, broken), clock=clock)

        runner.run_due()
        clock.now = 5.0
        runner.run_due()
        clock.now = 10.0
        runner.run_due()

        assert calls == [0.0, 10.0]

    def test_the_failure_is_logged_with_the_job_name(self, caplog):
        runner = make_runner(PeriodicJob("broken", 10.0, failing_action))

        with caplog.at_level(logging.ERROR, logger="janus_presence.jobs"):
            runner.run_due()

        assert "job broken failed" in caplog.text
        assert "disk on fire" in caplog.text

    def test_the_lock_is_released_after_a_failure(self):
        lock = CountingLock()
        runner = make_runner(PeriodicJob("broken", 10.0, failing_action), lock=lock)

        runner.run_due()

        assert lock.entries == 1
        assert not lock.active


class TestServiceLock:
    def test_each_job_runs_while_holding_the_lock(self):
        lock = CountingLock()
        held: list[bool] = []

        def action() -> object:
            held.append(lock.active)
            return None

        runner = make_runner(
            PeriodicJob("a", 1.0, action), PeriodicJob("b", 1.0, action), lock=lock
        )

        runner.run_due()

        assert held == [True, True]
        assert lock.entries == 2
        assert not lock.active


class TestResultLogging:
    def test_a_job_that_handled_items_says_how_many(self, caplog):
        runner = make_runner(PeriodicJob("close_stale_visits", 1.0, Counter(result=["v1", "v2"])))

        with caplog.at_level(logging.INFO, logger="janus_presence.jobs"):
            runner.run_due()

        assert "job close_stale_visits handled 2 item(s)" in caplog.text

    def test_a_job_that_handled_nothing_stays_quiet(self, caplog):
        runner = make_runner(PeriodicJob("close_stale_visits", 1.0, Counter(result=[])))

        with caplog.at_level(logging.INFO, logger="janus_presence.jobs"):
            runner.run_due()

        assert "handled" not in caplog.text


class FakeService:
    """The five duties the runner calls, each recording that it was called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def close_stale_visits(self) -> list[object]:
        self.calls.append("close_stale_visits")
        return []

    def close_due_clips(self) -> list[str]:
        self.calls.append("close_due_clips")
        return []

    def expire_snapshots(self) -> list[str]:
        self.calls.append("expire_snapshots")
        return []

    def enforce_retention(self) -> None:
        self.calls.append("enforce_retention")

    def forget_stale_unknowns(self) -> list[str]:
        self.calls.append("forget_stale_unknowns")
        return []


def jobs_for(visit_gap_s: float) -> list[PeriodicJob]:
    config = SimpleNamespace(visit_gap_s=visit_gap_s)
    return default_jobs(FakeService(), config)  # type: ignore[arg-type]


class TestDefaultJobs:
    def test_visits_and_clips_come_first_since_consumers_wait_on_them(self):
        names = [job.name for job in jobs_for(30)]

        assert names == [
            "close_stale_visits",
            "close_due_clips",
            "expire_snapshots",
            "enforce_retention",
            "forget_stale_unknowns",
        ]

    def test_every_duty_is_wired_to_its_service_method(self):
        service = FakeService()
        jobs = default_jobs(service, SimpleNamespace(visit_gap_s=30))  # type: ignore[arg-type]

        for job in jobs:
            job.action()

        assert service.calls == [job.name for job in jobs]

    @pytest.mark.parametrize(
        ("visit_gap_s", "expected_s"),
        [(30, 5.0), (300, 5.0), (9, 3.0), (3, 1.0), (1, 1.0)],
    )
    def test_the_visit_check_follows_the_gap_within_one_and_five_seconds(
        self, visit_gap_s, expected_s
    ):
        visit_job = jobs_for(visit_gap_s)[0]

        assert visit_job.interval_s == pytest.approx(expected_s)

    def test_the_default_jobs_run_together_without_clashing_names(self):
        service = FakeService()
        runner = JobRunner(
            default_jobs(service, SimpleNamespace(visit_gap_s=30)),  # type: ignore[arg-type]
            CountingLock(),
            FakeClock(),
        )

        assert len(runner.run_due()) == 5
        assert sorted(service.calls) == sorted(set(service.calls))


class TestThread:
    def test_the_thread_runs_due_jobs_until_stopped(self):
        ran = threading.Event()

        def action() -> object:
            ran.set()
            return None

        runner = JobRunner(
            [PeriodicJob("job", 0.01, action)], threading.RLock(), tick_s=0.005
        )

        runner.start()
        try:
            assert ran.wait(timeout=5.0)
        finally:
            runner.stop()

    def test_stopping_a_runner_that_never_started_is_harmless(self):
        make_runner(PeriodicJob("job", 1.0, Counter())).stop()
