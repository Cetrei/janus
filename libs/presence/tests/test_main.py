"""python -m janus_presence CLI (requisito 39): exit codes and what it says.

The heavy parts (cameras, models, the HTTP server) are replaced by fakes:
what is under test is the CLI's own contract, not the runner behind it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from janus_biometrics import BiometricsError

from janus_presence import __main__ as cli
from janus_presence.errors import PresenceError
from janus_presence.event_log import VISIT_ENDED, VISIT_STARTED, JsonlEventLog
from janus_presence.models import Visit

REVIEW_URL = "http://127.0.0.1:8765/"

CONFIG = """\
state_dir = "{state_dir}"

[presence]
match_threshold = 0.6
match_threshold_ambiguous = 1.2

[[sources]]
source_id = "cuarto"
kind = "camera"
device = 0
{extra}"""


def write_config(tmp_path: Path, extra: str = "") -> Path:
    text = CONFIG.format(state_dir=(tmp_path / "state").as_posix(), extra=extra)
    path = tmp_path / "presence.toml"
    path.write_text(text, encoding="utf-8")
    return path


def run_cli(config: Path, *flags: str) -> int:
    return cli.main(["run", "--config", str(config), *flags])


class FakeRunner:
    def __init__(self, review_url: str | None = REVIEW_URL) -> None:
        self.review_url = review_url


@pytest.fixture
def runs(monkeypatch) -> list[FakeRunner]:
    """Fakes the runner and records each one the CLI hands to run_until_signal."""
    started: list[FakeRunner] = []
    monkeypatch.setattr(cli, "build_runner", lambda config: FakeRunner())
    monkeypatch.setattr(cli, "run_until_signal", started.append)
    return started


class TestRun:
    def test_runs_the_runner_built_from_the_config_and_exits_cleanly(self, tmp_path, runs):
        code = run_cli(write_config(tmp_path))

        assert code == cli.EXIT_OK
        assert len(runs) == 1

    def test_announces_the_review_page_and_where_its_token_lives(self, tmp_path, runs, caplog):
        caplog.set_level(logging.INFO, logger="janus_presence.cli")

        run_cli(write_config(tmp_path))

        assert REVIEW_URL in caplog.text
        assert str(tmp_path / "state" / "presence" / "review.token") in caplog.text

    def test_says_which_sources_it_starts_with(self, tmp_path, runs, caplog):
        caplog.set_level(logging.INFO, logger="janus_presence.cli")

        run_cli(write_config(tmp_path))

        assert "cuarto" in caplog.text

    def test_says_so_when_the_review_page_is_disabled(self, tmp_path, runs, monkeypatch, caplog):
        caplog.set_level(logging.INFO, logger="janus_presence.cli")
        monkeypatch.setattr(cli, "build_runner", lambda config: FakeRunner(review_url=None))

        run_cli(write_config(tmp_path, "[review]\nenabled = false\n"))

        assert "disabled" in caplog.text
        assert REVIEW_URL not in caplog.text


class TestBadConfig:
    def test_a_missing_config_file_is_a_usage_error(self, tmp_path, runs, capsys):
        code = run_cli(tmp_path / "nope.toml")

        assert code == cli.EXIT_USAGE
        assert "Cannot read" in capsys.readouterr().err
        assert runs == []

    def test_an_invalid_config_names_the_offending_key(self, tmp_path, runs, capsys):
        code = run_cli(write_config(tmp_path, "unknown_key = 1\n"))

        assert code == cli.EXIT_USAGE
        assert "unknown_key" in capsys.readouterr().err
        assert runs == []


class TestFailures:
    @pytest.mark.parametrize(
        "error",
        [PresenceError("sample key missing"), BiometricsError("no model"), OSError("port busy")],
    )
    def test_errors_an_operator_can_fix_end_in_one_line_and_exit_1(
        self, tmp_path, monkeypatch, capsys, error
    ):
        def failing_build(config):
            raise error

        monkeypatch.setattr(cli, "build_runner", failing_build)
        monkeypatch.setattr(cli, "run_until_signal", lambda runner: pytest.fail("must not run"))

        code = run_cli(write_config(tmp_path))

        assert code == cli.EXIT_FAILURE
        assert f"Error: {error}" in capsys.readouterr().err

    def test_a_failure_while_running_also_exits_1(self, tmp_path, monkeypatch, capsys):
        def crash(runner):
            raise PresenceError("camera lost")

        monkeypatch.setattr(cli, "build_runner", lambda config: FakeRunner())
        monkeypatch.setattr(cli, "run_until_signal", crash)

        code = run_cli(write_config(tmp_path))

        assert code == cli.EXIT_FAILURE
        assert "camera lost" in capsys.readouterr().err

    def test_an_unexpected_exception_keeps_its_traceback(self, tmp_path, monkeypatch):
        def broken_build(config):
            raise RuntimeError("bug")

        monkeypatch.setattr(cli, "build_runner", broken_build)

        with pytest.raises(RuntimeError, match="bug"):
            run_cli(write_config(tmp_path))


LONG_AGO = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
ANA = "11111111-2222-3333-4444-555555555555"
BETO = "99999999-8888-7777-6666-555555555555"


def visits_cli(config: Path, *flags: str) -> int:
    return cli.main(["visits", "--config", str(config), *flags])


def presence_dir(tmp_path: Path) -> Path:
    return tmp_path / "state" / "presence"


def log_visit(
    tmp_path: Path, visit_id: str, person_id: str, started_at: datetime, seconds: int | None
) -> None:
    """Writes one visit into the default event log of `write_config`'s state dir."""
    ended = started_at + timedelta(seconds=seconds) if seconds is not None else None
    visit = Visit(visit_id, person_id, "cuarto", started_at, ended or started_at, ended)
    with JsonlEventLog(presence_dir(tmp_path) / "events.jsonl") as log:
        log.write(VISIT_STARTED, Visit(visit_id, person_id, "cuarto", started_at, started_at))
        if ended is not None:
            log.write(VISIT_ENDED, visit)


class TestVisits:
    def test_lists_the_visits_in_the_event_log_and_exits_cleanly(self, tmp_path, capsys):
        log_visit(tmp_path, "v1", ANA, LONG_AGO, 252)

        code = visits_cli(write_config(tmp_path))

        out = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "4m 12s" in out
        assert "sin nombre (11111111)" in out

    def test_names_come_from_the_presence_database_when_there_is_one(self, tmp_path, capsys):
        log_visit(tmp_path, "v1", ANA, LONG_AGO, 60)
        db = presence_dir(tmp_path) / "presence.db"
        connection = sqlite3.connect(db)
        connection.execute("CREATE TABLE persons (person_id TEXT PRIMARY KEY, label TEXT)")
        connection.execute("INSERT INTO persons VALUES (?, ?)", (ANA, "Ana"))
        connection.commit()
        connection.close()

        visits_cli(write_config(tmp_path))

        out = capsys.readouterr().out
        assert "Ana" in out
        assert "sin nombre" not in out

    def test_no_log_yet_is_not_an_error(self, tmp_path, capsys):
        code = visits_cli(write_config(tmp_path))

        assert code == cli.EXIT_OK
        assert "No hay visitas" in capsys.readouterr().out

    def test_json_prints_one_object_per_visit(self, tmp_path, capsys):
        log_visit(tmp_path, "v1", ANA, LONG_AGO, 60)
        log_visit(tmp_path, "v2", BETO, LONG_AGO + timedelta(hours=1), None)

        visits_cli(write_config(tmp_path), "--json")

        payload = json.loads(capsys.readouterr().out)
        assert [item["visit_id"] for item in payload] == ["v1", "v2"]
        assert payload[1]["ended_at"] is None

    def test_last_keeps_only_the_newest_visits(self, tmp_path, capsys):
        log_visit(tmp_path, "v1", ANA, LONG_AGO, 60)
        log_visit(tmp_path, "v2", BETO, LONG_AGO + timedelta(hours=1), 60)

        visits_cli(write_config(tmp_path), "--last", "1")

        out = capsys.readouterr().out
        assert "99999999" in out
        assert "11111111" not in out

    def test_since_drops_visits_older_than_that(self, tmp_path, capsys):
        log_visit(tmp_path, "v1", ANA, LONG_AGO, 60)

        visits_cli(write_config(tmp_path), "--since", "24h")

        assert "No hay visitas" in capsys.readouterr().out

    def test_a_missing_config_is_a_usage_error(self, tmp_path, capsys):
        code = visits_cli(tmp_path / "nope.toml")

        assert code == cli.EXIT_USAGE
        assert "Cannot read" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "flags",
        [["--since", "soon"], ["--since", "1.5h"], ["--last", "0"], ["--last", "many"]],
    )
    def test_a_flag_that_makes_no_sense_is_a_usage_error(self, tmp_path, flags):
        with pytest.raises(SystemExit) as exit_info:
            visits_cli(write_config(tmp_path), *flags)

        assert exit_info.value.code == cli.EXIT_USAGE

    def test_visits_needs_a_config(self):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["visits"])

        assert exit_info.value.code == cli.EXIT_USAGE


class TestCommandLine:
    def test_a_command_is_required(self):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([])

        assert exit_info.value.code == cli.EXIT_USAGE

    def test_run_needs_a_config(self):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["run"])

        assert exit_info.value.code == cli.EXIT_USAGE

    def test_log_level_must_be_a_known_level(self, tmp_path):
        with pytest.raises(SystemExit) as exit_info:
            run_cli(write_config(tmp_path), "--log-level", "loud")

        assert exit_info.value.code == cli.EXIT_USAGE
