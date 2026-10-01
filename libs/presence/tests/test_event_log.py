"""JSONL event log (requisito 39) and its wiring to the service (requisito 30)."""

from __future__ import annotations

import json
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from janus_presence.event_log import (
    PERSON_SEEN,
    VISIT_ENDED,
    VISIT_STARTED,
    JsonlEventLog,
    attach_event_log,
)
from janus_presence.models import PersonSeenEvent, Visit

STARTED = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class FakeService:
    """Captures the callbacks attach_event_log registers."""

    def __init__(self) -> None:
        self.started: list = []
        self.ended: list = []
        self.seen: list = []

    def on_visit_started(self, callback) -> None:
        self.started.append(callback)

    def on_visit_ended(self, callback) -> None:
        self.ended.append(callback)

    def on_person_seen(self, callback) -> None:
        self.seen.append(callback)


def make_visit(ended: bool = False) -> Visit:
    last_seen = STARTED + timedelta(seconds=12.5)
    return Visit(
        visit_id="v1",
        person_id="p1",
        source_id="cuarto",
        started_at=STARTED,
        last_seen_at=last_seen,
        ended_at=last_seen if ended else None,
    )


class TestJsonlEventLog:
    def test_each_event_is_one_json_line_with_timestamp_and_type(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with JsonlEventLog(path) as log:
            log.write("custom", {"a": 1})
            log.write("custom", {"a": 2})

        lines = read_lines(path)
        assert [line["data"] for line in lines] == [{"a": 1}, {"a": 2}]
        assert {line["type"] for line in lines} == {"custom"}
        assert all(datetime.fromisoformat(line["ts"]).tzinfo is not None for line in lines)

    def test_dataclasses_datetimes_and_paths_are_serialized(self, tmp_path):
        path = tmp_path / "events.jsonl"
        event = PersonSeenEvent(
            person_id="p1",
            known=False,
            first_seen=True,
            confidence=0.5,
            camera_id="cuarto",
            timestamp=STARTED,
            snapshot_ref=str(tmp_path / "snap.enc"),
        )
        with JsonlEventLog(path) as log:
            log.write(PERSON_SEEN, event)

        data = read_lines(path)[0]["data"]
        assert data["timestamp"] == STARTED.isoformat()
        assert data["first_seen"] is True

    def test_an_unserializable_event_is_dropped_without_raising(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with JsonlEventLog(path) as log:
            log.write("bad", {"value": object()})
            log.write("good", {"value": 1})

        assert [line["type"] for line in read_lines(path)] == ["good"]

    def test_an_unwritable_log_never_raises(self, tmp_path):
        log = JsonlEventLog(tmp_path)  # a directory cannot be opened as a file

        log.write("custom", {"a": 1})
        log.write("custom", {"a": 2})
        log.close()

    def test_writing_after_close_is_ignored(self, tmp_path):
        path = tmp_path / "events.jsonl"
        log = JsonlEventLog(path)
        log.write("custom", {"a": 1})
        log.close()

        log.write("custom", {"a": 2})

        assert len(read_lines(path)) == 1

    def test_a_full_file_is_rotated_to_a_single_backup(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with JsonlEventLog(path, max_bytes=50) as log:
            for number in (1, 2, 3):
                log.write("custom", {"n": number})

        backup = tmp_path / "events.jsonl.1"
        assert [line["data"]["n"] for line in read_lines(path)] == [3]
        assert [line["data"]["n"] for line in read_lines(backup)] == [2]

    def test_max_bytes_must_be_positive(self, tmp_path):
        with pytest.raises(ValueError, match="max_bytes"):
            JsonlEventLog(tmp_path / "events.jsonl", max_bytes=0)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
    def test_the_log_is_private(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with JsonlEventLog(path) as log:
            log.write("custom", {"a": 1})

        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestAttachEventLog:
    def test_visit_events_are_logged_and_the_ended_one_carries_the_dwell_time(self, tmp_path):
        path = tmp_path / "events.jsonl"
        service = FakeService()
        with JsonlEventLog(path) as log:
            attach_event_log(service, log)
            service.started[0](make_visit())
            service.ended[0](make_visit(ended=True))

        started, ended = read_lines(path)
        assert started["type"] == VISIT_STARTED
        assert "dwell_s" not in started["data"]
        assert ended["type"] == VISIT_ENDED
        assert ended["data"]["dwell_s"] == 12.5

    def test_person_seen_is_only_logged_when_asked_for(self, tmp_path):
        service = FakeService()
        with JsonlEventLog(tmp_path / "events.jsonl") as log:
            attach_event_log(service, log)

        assert service.seen == []

        service = FakeService()
        with JsonlEventLog(tmp_path / "other.jsonl") as log:
            attach_event_log(service, log, include_person_seen=True)

        assert len(service.seen) == 1
