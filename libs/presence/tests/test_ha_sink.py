"""Home Assistant sink (SPEC.md ampliación 2026-09-30, requisito 42)."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from janus_presence import ha_sink
from janus_presence.errors import PresenceError
from janus_presence.ha_sink import HomeAssistantSink, load_token, post_event
from janus_presence.models import IdentityState, PersonRecord, Visit
from janus_presence.runner_config import RunnerConfigError, load_runner_config

NOW = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
WAIT_S = 5.0


def make_visit(person_id: str = "p1", ended: bool = False) -> Visit:
    return Visit(
        visit_id="v1",
        person_id=person_id,
        source_id="entrada",
        started_at=NOW,
        last_seen_at=NOW + timedelta(seconds=40),
        ended_at=NOW + timedelta(seconds=70) if ended else None,
    )


def make_person(
    person_id: str, state: IdentityState, label: str | None, role: str | None = None
) -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        state=state,
        embedding_ids=[],
        first_seen_at=NOW,
        last_seen_at=NOW,
        label=label,
        role=role,
    )


class FakeService:
    def __init__(self, people: list[PersonRecord]) -> None:
        self._people = {person.person_id: person for person in people}
        self.started_callbacks: list[Any] = []
        self.ended_callbacks: list[Any] = []

    def get_person(self, person_id: str) -> PersonRecord | None:
        return self._people.get(person_id)

    def on_visit_started(self, callback: Any) -> None:
        self.started_callbacks.append(callback)

    def on_visit_ended(self, callback: Any) -> None:
        self.ended_callbacks.append(callback)


def make_sink(post: Any, max_queue: int = 10) -> HomeAssistantSink:
    return HomeAssistantSink("http://127.0.0.1:8123", "token", max_queue=max_queue, post=post)


class TestPayload:
    def test_should_include_name_and_role_when_the_person_is_known(self) -> None:
        # Arrange
        owner = make_person("p1", IdentityState.ESTABLISHED, "Joanfer", "owner")
        service = FakeService([owner])
        sink = make_sink(lambda *args: None)
        sink.attach(service)  # type: ignore[arg-type]
        # Act
        payload = sink._payload("visit_started", make_visit())
        # Assert
        assert payload["label"] == "Joanfer"
        assert payload["role"] == "owner"
        assert payload["state"] == "established"
        assert payload["source_id"] == "entrada"
        assert "dwell_s" not in payload

    def test_should_send_null_name_and_role_when_the_person_is_unknown(self) -> None:
        # Arrange
        stranger = make_person("p2", IdentityState.UNKNOWN, None)
        sink = make_sink(lambda *args: None)
        sink.attach(FakeService([stranger]))  # type: ignore[arg-type]
        # Act
        payload = sink._payload("visit_started", make_visit("p2"))
        # Assert
        assert payload["label"] is None
        assert payload["role"] is None
        assert payload["state"] == "unknown"

    def test_should_treat_a_forgotten_person_as_unknown(self) -> None:
        # Arrange
        sink = make_sink(lambda *args: None)
        sink.attach(FakeService([]))  # type: ignore[arg-type]
        # Act
        payload = sink._payload("visit_ended", make_visit("gone"))
        # Assert
        assert payload["person_id"] == "gone"
        assert payload["label"] is None
        assert payload["state"] == "unknown"

    def test_should_include_dwell_time_when_the_visit_ended(self) -> None:
        # Arrange
        sink = make_sink(lambda *args: None)
        sink.attach(FakeService([]))  # type: ignore[arg-type]
        # Act
        payload = sink._payload("visit_ended", make_visit(ended=True))
        # Assert
        assert payload["dwell_s"] == 70.0
        assert payload["at"] == (NOW + timedelta(seconds=70)).isoformat()


class TestDelivery:
    def test_should_deliver_visit_events_through_the_worker_thread(self) -> None:
        # Arrange
        delivered: list[dict[str, Any]] = []
        done = threading.Event()

        def post(url: str, token: str, payload: dict[str, Any], timeout_s: float) -> None:
            delivered.append(payload)
            if len(delivered) == 2:
                done.set()

        owner = make_person("p1", IdentityState.ESTABLISHED, "Joanfer", "owner")
        service = FakeService([owner])
        sink = make_sink(post)
        sink.attach(service)  # type: ignore[arg-type]
        sink.start()
        try:
            # Act
            service.started_callbacks[0](make_visit())
            service.ended_callbacks[0](make_visit(ended=True))
            assert done.wait(WAIT_S)
        finally:
            sink.stop()
        # Assert
        assert [payload["kind"] for payload in delivered] == ["visit_started", "visit_ended"]

    def test_should_retry_and_then_succeed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange
        monkeypatch.setattr(ha_sink, "_BACKOFF_BASE_S", 0.0)
        attempts: list[int] = []

        def post(url: str, token: str, payload: dict[str, Any], timeout_s: float) -> None:
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("home assistant is restarting")

        sink = make_sink(post)
        # Act
        sink._deliver({"kind": "visit_started"})
        # Assert
        assert len(attempts) == 3

    def test_should_give_up_after_the_last_attempt_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        monkeypatch.setattr(ha_sink, "_BACKOFF_BASE_S", 0.0)
        attempts: list[int] = []

        def post(url: str, token: str, payload: dict[str, Any], timeout_s: float) -> None:
            attempts.append(1)
            raise OSError("unreachable")

        sink = make_sink(post)
        # Act
        sink._deliver({"kind": "visit_started"})
        # Assert
        assert len(attempts) == ha_sink._MAX_ATTEMPTS

    def test_should_drop_the_oldest_event_when_the_queue_is_full(self) -> None:
        # Arrange
        sink = make_sink(lambda *args: None, max_queue=2)
        # Act
        for number in range(3):
            sink._enqueue({"kind": f"event-{number}"})
        # Assert
        kept = [sink._queue.get_nowait()["kind"] for _ in range(sink._queue.qsize())]
        assert kept == ["event-1", "event-2"]

    def test_should_not_raise_into_the_service_when_the_payload_fails(self) -> None:
        # Arrange
        class BrokenService(FakeService):
            def get_person(self, person_id: str) -> PersonRecord | None:
                raise RuntimeError("database closed")

        sink = make_sink(lambda *args: None)
        sink.attach(BrokenService([]))  # type: ignore[arg-type]
        # Act
        sink._on_visit("visit_started", make_visit())
        # Assert
        assert sink._queue.qsize() == 0

    def test_should_stop_cleanly_when_it_never_started(self) -> None:
        sink = make_sink(lambda *args: None)
        sink.stop()
        sink.stop()


class TestPostEvent:
    def test_should_post_json_with_the_bearer_token_to_the_events_endpoint(self) -> None:
        # Arrange
        received: list[tuple[str, str | None, dict[str, Any]]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                received.append((self.path, self.headers["Authorization"], body))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: object) -> None:
                return None

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Act
            post_event(f"http://127.0.0.1:{server.server_port}/", "secret", {"kind": "x"}, 2.0)
        finally:
            server.shutdown()
            server.server_close()
        # Assert
        assert received == [("/api/events/janus_presence", "Bearer secret", {"kind": "x"})]


class TestConstruction:
    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host", "no-scheme", "http://"])
    def test_should_reject_urls_that_are_not_http_or_https(self, url: str) -> None:
        with pytest.raises(ValueError):
            HomeAssistantSink(url, "token")

    def test_should_reject_an_empty_token(self) -> None:
        with pytest.raises(ValueError):
            HomeAssistantSink("http://127.0.0.1:8123", "")


class TestLoadToken:
    def test_should_read_and_strip_a_private_token_file(self, tmp_path: Path) -> None:
        # Arrange
        path = tmp_path / "ha.token"
        path.write_text("abc123\n", encoding="utf-8")
        path.chmod(0o600)
        # Act / Assert
        assert load_token(path) == "abc123"

    def test_should_fail_when_the_file_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(PresenceError, match="does not exist"):
            load_token(tmp_path / "missing.token")

    def test_should_fail_when_the_file_is_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "ha.token"
        path.write_text("  \n", encoding="utf-8")
        path.chmod(0o600)
        with pytest.raises(PresenceError, match="empty"):
            load_token(path)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_should_refuse_a_token_readable_by_other_users(self, tmp_path: Path) -> None:
        path = tmp_path / "ha.token"
        path.write_text("abc123", encoding="utf-8")
        path.chmod(0o644)
        with pytest.raises(PresenceError, match="readable by other users"):
            load_token(path)


class TestRunnerConfigSection:
    @staticmethod
    def write_config(tmp_path: Path, extra: str) -> Path:
        path = tmp_path / "presence.toml"
        path.write_text(
            f'state_dir = "{tmp_path.as_posix()}"\n'
            "[presence]\nmatch_threshold = 0.6\nmatch_threshold_ambiguous = 1.2\n"
            '[[sources]]\nsource_id = "entrada"\nkind = "camera"\ndevice = 0\n' + extra,
            encoding="utf-8",
        )
        return path

    def test_should_be_off_without_the_section(self, tmp_path: Path) -> None:
        config = load_runner_config(self.write_config(tmp_path, ""))
        assert config.home_assistant is None

    def test_should_parse_the_section(self, tmp_path: Path) -> None:
        # Arrange
        extra = (
            '[home_assistant]\nurl = "http://127.0.0.1:8123"\n'
            f'token_file = "{tmp_path.as_posix()}/ha.token"\n'
        )
        # Act
        config = load_runner_config(self.write_config(tmp_path, extra))
        # Assert
        assert config.home_assistant is not None
        assert config.home_assistant.url == "http://127.0.0.1:8123"
        assert config.home_assistant.token_file == tmp_path / "ha.token"

    def test_should_reject_a_url_that_is_not_http(self, tmp_path: Path) -> None:
        extra = '[home_assistant]\nurl = "file:///tmp/x"\ntoken_file = "/tmp/t"\n'
        with pytest.raises(RunnerConfigError, match="http"):
            load_runner_config(self.write_config(tmp_path, extra))

    def test_should_reject_unknown_keys_in_the_section(self, tmp_path: Path) -> None:
        extra = '[home_assistant]\nurl = "http://h:1"\ntoken_file = "/tmp/t"\ntoken = "oops"\n'
        with pytest.raises(RunnerConfigError):
            load_runner_config(self.write_config(tmp_path, extra))
