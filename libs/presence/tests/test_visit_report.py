"""Visit report (requisito 47): the event log read back as visits. The log is
written by the real `JsonlEventLog`, so what is tested is the round trip, not
a hand made format."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from janus_presence.event_log import VISIT_ENDED, VISIT_STARTED, JsonlEventLog, backup_path
from janus_presence.models import Visit
from janus_presence.visit_report import (
    VisitRow,
    format_dwell,
    log_paths,
    parse_duration,
    read_labels,
    read_visits,
    render_json,
    render_visits,
    select_visits,
)

T0 = datetime(2026, 9, 30, 18, 0, 0, tzinfo=UTC)
ANA = "11111111-2222-3333-4444-555555555555"
BETO = "99999999-8888-7777-6666-555555555555"


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def make_visit(
    visit_id: str,
    person_id: str = ANA,
    start_s: int = 0,
    end_s: int | None = None,
    source_id: str = "cuarto",
) -> Visit:
    ended = at(end_s) if end_s is not None else None
    return Visit(visit_id, person_id, source_id, at(start_s), at(end_s or start_s), ended)


def write_events(path: Path, *events: tuple[str, Visit]) -> None:
    with JsonlEventLog(path) as log:
        for event_type, visit in events:
            log.write(event_type, visit)


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "events.jsonl"


class TestReadVisits:
    def test_a_started_and_an_ended_line_make_one_closed_visit(self, log_path):
        write_events(
            log_path,
            (VISIT_STARTED, make_visit("v1")),
            (VISIT_ENDED, make_visit("v1", end_s=252)),
        )

        [row] = read_visits([log_path])

        assert row == VisitRow("v1", ANA, "cuarto", at(0), at(252))
        assert row.dwell_s == 252

    def test_a_visit_without_an_end_line_is_open(self, log_path):
        write_events(log_path, (VISIT_STARTED, make_visit("v1")))

        [row] = read_visits([log_path])

        assert row.ended_at is None
        assert row.dwell_s is None

    def test_a_visit_whose_start_line_was_rotated_away_still_shows_up(self, log_path):
        write_events(log_path, (VISIT_ENDED, make_visit("v1", end_s=60)))

        [row] = read_visits([log_path])

        assert row.started_at == at(0)
        assert row.dwell_s == 60

    def test_a_start_line_never_reopens_a_visit_already_ended(self, log_path):
        write_events(
            log_path,
            (VISIT_ENDED, make_visit("v1", end_s=60)),
            (VISIT_STARTED, make_visit("v1")),
        )

        [row] = read_visits([log_path])

        assert row.ended_at == at(60)

    def test_visits_come_oldest_first(self, log_path):
        write_events(
            log_path,
            (VISIT_STARTED, make_visit("late", start_s=500)),
            (VISIT_STARTED, make_visit("early", start_s=10)),
        )

        assert [row.visit_id for row in read_visits([log_path])] == ["early", "late"]

    def test_lines_that_are_not_visit_events_are_skipped(self, log_path):
        write_events(log_path, (VISIT_STARTED, make_visit("v1")))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("not json at all\n")
            handle.write('{"ts": "x", "type": "person_seen", "data": {"person_id": "p"}}\n')
            handle.write('{"ts": "x", "type": "visit_started", "data": {"visit_id": 7}}\n')
            handle.write("[1, 2]\n")
            handle.write('{"type": "visit_started", "data": {"visit_id"')

        assert [row.visit_id for row in read_visits([log_path])] == ["v1"]

    def test_a_missing_log_is_no_visits(self, tmp_path):
        assert read_visits(log_paths(tmp_path / "events.jsonl")) == []

    def test_the_backup_is_read_before_the_current_log(self, log_path):
        write_events(backup_path(log_path), (VISIT_STARTED, make_visit("old", start_s=0)))
        write_events(log_path, (VISIT_STARTED, make_visit("new", start_s=100)))

        rows = read_visits(log_paths(log_path))

        assert [row.visit_id for row in rows] == ["old", "new"]

    def test_a_visit_split_across_the_backup_and_the_log_is_one_visit(self, log_path):
        write_events(backup_path(log_path), (VISIT_STARTED, make_visit("v1")))
        write_events(log_path, (VISIT_ENDED, make_visit("v1", end_s=90)))

        [row] = read_visits(log_paths(log_path))

        assert row.dwell_s == 90


class TestSelect:
    def rows(self) -> list[VisitRow]:
        return [VisitRow(f"v{index}", ANA, "cuarto", at(index * 100), None) for index in range(4)]

    def test_nothing_selected_means_everything(self):
        assert select_visits(self.rows()) == self.rows()

    def test_since_keeps_visits_that_started_at_or_after_it(self):
        selected = select_visits(self.rows(), since=at(100))

        assert [row.visit_id for row in selected] == ["v1", "v2", "v3"]

    def test_last_keeps_the_newest_ones(self):
        selected = select_visits(self.rows(), last=2)

        assert [row.visit_id for row in selected] == ["v2", "v3"]

    def test_since_is_applied_before_last(self):
        selected = select_visits(self.rows(), since=at(200), last=5)

        assert [row.visit_id for row in selected] == ["v2", "v3"]


class TestDuration:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("90m", timedelta(minutes=90)),
            ("12h", timedelta(hours=12)),
            ("7d", timedelta(days=7)),
            (" 2H ", timedelta(hours=2)),
        ],
    )
    def test_minutes_hours_and_days_are_understood(self, text, expected):
        assert parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["", "7", "d", "1.5h", "-3h", "2w", "1h30m"])
    def test_anything_else_says_what_is_accepted(self, text):
        with pytest.raises(ValueError, match="90m, 12h or 7d"):
            parse_duration(text)

    @pytest.mark.parametrize(
        ("seconds", "text"),
        [(0, "0s"), (45, "45s"), (252, "4m 12s"), (3600, "1h 00m"), (7500, "2h 05m")],
    )
    def test_a_dwell_is_shown_in_its_two_largest_units(self, seconds, text):
        assert format_dwell(seconds) == text


class TestRender:
    def test_a_table_names_the_person_the_source_and_the_dwell(self):
        rows = [VisitRow("v1", ANA, "cuarto", at(0), at(252))]

        table = render_visits(rows, {ANA: "Ana"}, tz=UTC)

        assert "2026-09-30 18:00:00" in table
        assert "2026-09-30 18:04:12" in table
        assert "4m 12s" in table
        assert "cuarto" in table
        assert "Ana" in table

    def test_a_person_without_a_name_shows_a_short_id(self):
        rows = [VisitRow("v1", BETO, "cuarto", at(0), None)]

        table = render_visits(rows, {}, tz=UTC)

        assert "sin nombre (99999999)" in table
        assert BETO not in table

    def test_an_open_visit_says_so_instead_of_a_time(self):
        rows = [VisitRow("v1", ANA, "cuarto", at(0), None)]

        assert "en curso" in render_visits(rows, {ANA: "Ana"}, tz=UTC)

    def test_no_visits_says_so(self):
        assert render_visits([], {}) == "No hay visitas en el rango pedido."

    def test_json_has_one_object_per_visit_with_the_name_when_known(self):
        rows = [
            VisitRow("v1", ANA, "cuarto", at(0), at(60)),
            VisitRow("v2", BETO, "jardin", at(100), None),
        ]

        payload = json.loads(render_json(rows, {ANA: "Ana"}))

        assert payload[0]["label"] == "Ana"
        assert payload[0]["dwell_s"] == 60
        assert payload[0]["started_at"] == at(0).isoformat()
        assert payload[1]["label"] is None
        assert payload[1]["ended_at"] is None
        assert payload[1]["dwell_s"] is None


class TestLabels:
    def make_db(self, path: Path, rows: list[tuple[str, str | None]]) -> None:
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE persons (person_id TEXT PRIMARY KEY, label TEXT)")
        connection.executemany("INSERT INTO persons VALUES (?, ?)", rows)
        connection.commit()
        connection.close()

    def test_names_come_from_the_persons_table(self, tmp_path):
        db = tmp_path / "presence.db"
        self.make_db(db, [(ANA, "Ana"), (BETO, None)])

        assert read_labels(db) == {ANA: "Ana"}

    def test_a_missing_database_gives_no_names(self, tmp_path):
        assert read_labels(tmp_path / "presence.db") == {}

    def test_a_database_this_version_does_not_know_gives_no_names(self, tmp_path):
        db = tmp_path / "presence.db"
        sqlite3.connect(db).close()

        assert read_labels(db) == {}

    def test_reading_names_never_writes_to_the_database(self, tmp_path):
        db = tmp_path / "presence.db"
        self.make_db(db, [(ANA, "Ana")])
        before = db.read_bytes()

        read_labels(db)

        assert db.read_bytes() == before
