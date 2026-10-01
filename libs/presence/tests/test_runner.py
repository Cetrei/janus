"""The autonomous runner (requisito 39): start and stop order, a shutdown that
keeps going when a step fails, the sample key rules and the build wiring.
Cameras, models and the network are never touched: the parts are fakes."""

from __future__ import annotations

import logging
import os
import signal
import socket
import stat
import threading
from unittest.mock import MagicMock

import pytest

from janus_presence import runner as runner_module
from janus_presence.errors import PresenceError
from janus_presence.models import PresenceConfig, SourceConfig, SourceKind, SourceLocation
from janus_presence.monitor import DEFAULT_SAMPLE_FPS
from janus_presence.runner import PresenceRunner, build_runner, run_until_signal
from janus_presence.runner_config import load_runner_config
from janus_presence.store import PresenceStore

KEY_BYTES = 32
STOP_DELAY_S = 0.1
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="file modes and POSIX signals")


class Part:
    """A collaborator of PresenceRunner that records what it is asked to do.
    `failing` lists the actions that raise."""

    url = "http://127.0.0.1:1/"

    def __init__(self, name: str, events: list[str], failing: tuple[str, ...] = ()) -> None:
        self._name = name
        self._events = events
        self._failing = failing

    def start(self) -> None:
        self._do("start")

    def stop(self) -> None:
        self._do("stop")

    def close(self) -> None:
        self._do("close")

    def _do(self, action: str) -> None:
        self._events.append(f"{self._name}.{action}")
        if action in self._failing:
            raise RuntimeError(f"{self._name} {action} failed")


def make_runner(
    events: list[str], review: bool = True, failing: dict[str, tuple[str, ...]] | None = None
) -> PresenceRunner:
    failing = failing or {}

    def part(name: str) -> Part:
        return Part(name, events, failing.get(name, ()))

    return PresenceRunner(
        service=part("service"),
        monitor=part("monitor"),
        jobs=part("jobs"),
        frame_sources=part("cameras"),
        event_log=part("event_log"),
        review=part("review") if review else None,
    )


class TestStartAndStop:
    def test_jobs_start_first_then_cameras_then_the_review_page(self):
        events: list[str] = []

        make_runner(events).start()

        assert events == ["jobs.start", "monitor.start", "review.start"]

    def test_inputs_stop_before_the_service_and_the_event_log_closes_last(self):
        events: list[str] = []

        make_runner(events).stop()

        assert events == [
            "review.stop",
            "monitor.stop",
            "jobs.stop",
            "cameras.close",
            "service.close",
            "event_log.close",
        ]

    def test_without_a_review_page_there_is_nothing_to_start_or_stop(self):
        events: list[str] = []
        runner = make_runner(events, review=False)

        runner.start()
        runner.stop()

        assert not [event for event in events if event.startswith("review")]
        assert runner.review_url is None

    def test_the_review_url_is_the_pages_own(self):
        assert make_runner([]).review_url == Part.url

    def test_a_step_that_fails_does_not_stop_the_rest_of_the_shutdown(self, caplog):
        events: list[str] = []
        runner = make_runner(events, failing={"monitor": ("stop",), "jobs": ("stop",)})

        with caplog.at_level(logging.ERROR, logger="janus_presence.runner"):
            runner.stop()

        assert events[-3:] == ["cameras.close", "service.close", "event_log.close"]
        assert caplog.text.count("shutdown step") == 2

    def test_the_database_still_closes_when_the_cameras_fail_to_close(self):
        events: list[str] = []

        make_runner(events, failing={"cameras": ("close",)}).stop()

        assert "service.close" in events

    def test_stopping_twice_is_safe(self):
        events: list[str] = []
        runner = make_runner(events)

        runner.stop()
        runner.stop()

        assert len(events) == 12


class LifecycleRunner:
    def __init__(self, start_error: Exception | None = None) -> None:
        self.events: list[str] = []
        self._start_error = start_error

    def start(self) -> None:
        self.events.append("start")
        if self._start_error is not None:
            raise self._start_error

    def stop(self) -> None:
        self.events.append("stop")


class TestRunUntilSignal:
    def test_runs_until_the_stop_event_and_then_shuts_down(self):
        runner = LifecycleRunner()
        stop = threading.Event()
        threading.Timer(STOP_DELAY_S, stop.set).start()

        run_until_signal(runner, stop)

        assert runner.events == ["start", "stop"]

    def test_shuts_down_even_when_starting_fails(self):
        runner = LifecycleRunner(start_error=RuntimeError("camera exploded"))

        with pytest.raises(RuntimeError, match="camera exploded"):
            run_until_signal(runner, threading.Event())

        assert runner.events == ["start", "stop"]

    @POSIX_ONLY
    def test_sigterm_stops_it_and_the_previous_handlers_come_back(self):
        runner = LifecycleRunner()
        before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
        threading.Timer(STOP_DELAY_S, os.kill, args=(os.getpid(), signal.SIGTERM)).start()

        run_until_signal(runner)

        after = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
        assert runner.events == ["start", "stop"]
        assert after == before

    def test_off_the_main_thread_it_leaves_the_signal_handlers_alone(self):
        runner = LifecycleRunner()
        stop = threading.Event()
        before = signal.getsignal(signal.SIGINT)
        worker = threading.Thread(target=run_until_signal, args=(runner, stop))

        worker.start()
        stop.set()
        worker.join(timeout=5)

        assert runner.events == ["start", "stop"]
        assert signal.getsignal(signal.SIGINT) == before


class TestSampleKey:
    def test_the_first_run_creates_a_key_of_the_right_size(self, tmp_path):
        key = runner_module._load_or_create_key(tmp_path)

        assert len(key) == KEY_BYTES
        assert (tmp_path / "presence.key").read_bytes() == key

    @POSIX_ONLY
    def test_a_new_key_is_private_to_the_user(self, tmp_path):
        runner_module._load_or_create_key(tmp_path)

        mode = stat.S_IMODE((tmp_path / "presence.key").stat().st_mode)

        assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0

    def test_the_same_key_comes_back_on_the_next_run(self, tmp_path):
        first = runner_module._load_or_create_key(tmp_path)

        assert runner_module._load_or_create_key(tmp_path) == first

    def test_a_missing_key_next_to_existing_data_is_an_error_not_a_new_key(self, tmp_path):
        (tmp_path / "presence.db").write_bytes(b"")

        with pytest.raises(PresenceError, match="missing"):
            runner_module._load_or_create_key(tmp_path)

        assert not (tmp_path / "presence.key").exists()

    @POSIX_ONLY
    def test_a_key_readable_by_other_users_is_refused(self, tmp_path):
        runner_module._load_or_create_key(tmp_path)
        os.chmod(tmp_path / "presence.key", 0o644)

        with pytest.raises(PresenceError, match="readable by other users"):
            runner_module._load_or_create_key(tmp_path)

    @POSIX_ONLY
    def test_a_key_of_the_wrong_size_is_refused(self, tmp_path):
        path = tmp_path / "presence.key"
        path.write_bytes(b"x" * 16)
        os.chmod(path, 0o600)

        with pytest.raises(PresenceError, match="expected 32"):
            runner_module._load_or_create_key(tmp_path)


def camera(source_id: str, fps: float | None) -> SourceConfig:
    return SourceConfig(
        source_id, SourceKind.CAMERA, SourceLocation.LOCAL, "0", source_id, sample_fps=fps
    )


class TestRecorderRate:
    def test_the_highest_camera_rate_is_used_and_the_mismatch_is_logged(self, caplog):
        cameras = [camera("cuarto", 2), camera("jardin", 4)]

        with caplog.at_level(logging.WARNING, logger="janus_presence.runner"):
            fps = runner_module._recorder_fps(cameras)

        assert fps == 4
        assert "different rates" in caplog.text

    def test_cameras_at_the_same_rate_log_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger="janus_presence.runner"):
            fps = runner_module._recorder_fps([camera("a", 3), camera("b", 3)])

        assert fps == 3
        assert caplog.text == ""

    def test_a_camera_without_a_rate_uses_the_default(self):
        assert runner_module._recorder_fps([camera("cuarto", None)]) == DEFAULT_SAMPLE_FPS

    def test_no_cameras_uses_the_default(self):
        assert runner_module._recorder_fps([]) == DEFAULT_SAMPLE_FPS


class TestUnwiredWarnings:
    def config(self, **overrides) -> PresenceConfig:
        return PresenceConfig(0.6, 1.2, **overrides)

    def test_a_microphone_is_reported_as_ignored(self, caplog):
        mic = SourceConfig("mic", SourceKind.MICROPHONE, SourceLocation.LOCAL, "default", "mic")

        with caplog.at_level(logging.WARNING, logger="janus_presence.runner"):
            runner_module._warn_about_unwired(self.config(sources=[camera("c", 4), mic]))

        assert "audio is not wired" in caplog.text

    def test_voice_thresholds_are_reported_as_unused(self, caplog):
        config = self.config(
            sources=[camera("c", 4)],
            voice_match_threshold=0.5,
            voice_match_threshold_ambiguous=1.0,
        )

        with caplog.at_level(logging.WARNING, logger="janus_presence.runner"):
            runner_module._warn_about_unwired(config)

        assert "voice thresholds" in caplog.text

    def test_no_enabled_camera_is_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger="janus_presence.runner"):
            runner_module._warn_about_unwired(self.config(sources=[]))

        assert "nothing will be observed" in caplog.text

    def test_a_plain_camera_setup_logs_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger="janus_presence.runner"):
            runner_module._warn_about_unwired(self.config(sources=[camera("c", 4)]))

        assert caplog.text == ""


def write_config(tmp_path, review: str = "[review]\nenabled = false\n"):
    text = (
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        "[presence]\nmatch_threshold = 0.6\nmatch_threshold_ambiguous = 1.2\n"
        '[[sources]]\nsource_id = "cuarto"\nkind = "camera"\ndevice = 0\n'
        f"{review}"
    )
    path = tmp_path / "presence.toml"
    path.write_text(text, encoding="utf-8")
    return load_runner_config(path)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class RecordingStore(PresenceStore):
    opened: list[RecordingStore] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.close_calls = 0
        RecordingStore.opened.append(self)

    def close(self) -> None:
        self.close_calls += 1
        super().close()


@pytest.fixture
def fake_service(monkeypatch) -> MagicMock:
    """build_runner with a stand-in for the perception core, so nothing loads
    models or opens a camera. The store, monitor, jobs and event log are real."""
    service = MagicMock()
    RecordingStore.opened.clear()
    monkeypatch.setattr(runner_module, "PresenceStore", RecordingStore)
    monkeypatch.setattr(runner_module, "_build_service", lambda *args: service)
    return service


class TestBuildRunner:
    def test_builds_a_runner_wired_to_the_service_and_logs_visits(self, tmp_path, fake_service):
        runner = build_runner(write_config(tmp_path))

        try:
            fake_service.on_visit_started.assert_called_once()
            fake_service.on_visit_ended.assert_called_once()
            fake_service.on_person_seen.assert_not_called()
            assert runner.review_url is None
        finally:
            runner.stop()

    def test_the_sample_key_is_created_in_the_presence_directory(self, tmp_path, fake_service):
        runner = build_runner(write_config(tmp_path))
        runner.stop()

        assert (tmp_path / "state" / "presence" / "presence.key").exists()

    def test_the_review_page_is_built_on_the_configured_port_with_a_private_token(
        self, tmp_path, fake_service
    ):
        port = free_port()
        runner = build_runner(write_config(tmp_path, f"[review]\nport = {port}\n"))

        try:
            assert runner.review_url == f"http://127.0.0.1:{port}/"
            assert (tmp_path / "state" / "presence" / "review.token").exists()
        finally:
            runner.stop()

    def test_stopping_the_runner_closes_the_service(self, tmp_path, fake_service):
        runner = build_runner(write_config(tmp_path))

        runner.stop()

        fake_service.close.assert_called_once()

    def test_a_failure_building_the_service_closes_the_database(self, tmp_path, monkeypatch):
        RecordingStore.opened.clear()
        monkeypatch.setattr(runner_module, "PresenceStore", RecordingStore)

        def failing_build(*args):
            raise RuntimeError("models missing")

        monkeypatch.setattr(runner_module, "_build_service", failing_build)

        with pytest.raises(RuntimeError, match="models missing"):
            build_runner(write_config(tmp_path))

        assert [store.close_calls for store in RecordingStore.opened] == [1]

    def test_a_failure_after_the_service_exists_closes_it(
        self, tmp_path, fake_service, monkeypatch
    ):
        def failing_attach(*args, **kwargs):
            raise RuntimeError("cannot attach")

        monkeypatch.setattr(runner_module, "attach_event_log", failing_attach)

        with pytest.raises(RuntimeError, match="cannot attach"):
            build_runner(write_config(tmp_path))

        fake_service.close.assert_called_once()
