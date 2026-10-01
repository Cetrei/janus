"""Reads the JSONL event log back as a list of visits (SPEC.md, requisito 47):
who came and went, and for how long.

`python -m janus_presence visits` is the thin command over this module. The
log is the record of truth for the Home Loop milestone: it holds one
`visit_started` and one `visit_ended` line per visit, and this module pairs
them by `visit_id`. Three rules shape it:

* **Reading never fails on a bad line.** The runner may be writing the last
  line while this reads it, and a disk problem can truncate one. A line that
  is not valid JSON, or not a visit event, is skipped.
* **Both log files count.** When the log reaches its size limit the runner
  moves it to a single backup. Reading the backup first keeps visits from
  disappearing at the moment of rotation.
* **Names are optional.** The log holds ids only (event_log.py). Names come
  from the presence database, opened read only, and when that is not possible
  the report falls back to the ids instead of failing.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from janus_presence.event_log import VISIT_ENDED, VISIT_STARTED, backup_path

__all__ = [
    "VisitRow",
    "format_dwell",
    "log_paths",
    "parse_duration",
    "read_labels",
    "read_visits",
    "render_json",
    "render_visits",
    "select_visits",
]

_log = logging.getLogger(__name__)

_DURATION = re.compile(r"(\d+)([mhd])")
_UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SHORT_ID_CHARS = 8
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_DB_TIMEOUT_S = 2.0
_NO_VISITS = "No hay visitas en el rango pedido."
_OPEN_VISIT = "en curso"


@dataclass(frozen=True)
class VisitRow:
    visit_id: str
    person_id: str
    source_id: str
    started_at: datetime
    ended_at: datetime | None

    @property
    def dwell_s(self) -> float | None:
        """None while the visit is still open."""
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds()


def log_paths(path: Path) -> list[Path]:
    """The files to read, oldest first: the backup, then the current log."""
    return [backup_path(path), Path(path)]


def parse_duration(text: str) -> timedelta:
    """`90m`, `12h` or `7d`. Anything else is a ValueError that says what is
    accepted."""
    match = _DURATION.fullmatch(text.strip().lower())
    if match is None:
        raise ValueError(f"'{text}' is not a duration like 90m, 12h or 7d")
    return int(match.group(1)) * _UNITS[match.group(2)]


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _records(paths: Iterable[Path]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every well formed `(type, data)` pair. A file that does not exist yet
    (no backup before the first rotation) is simply empty."""
    for path in paths:
        try:
            handle = path.open(encoding="utf-8")
        except FileNotFoundError:
            continue
        with handle:
            for line in handle:
                record = _decode(line)
                if record is not None:
                    yield record


def _decode(line: str) -> tuple[str, Mapping[str, Any]] | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    event_type = record.get("type")
    data = record.get("data")
    if not isinstance(event_type, str) or not isinstance(data, dict):
        return None
    return event_type, data


def _row_from(data: Mapping[str, Any]) -> VisitRow | None:
    visit_id = data.get("visit_id")
    person_id = data.get("person_id")
    source_id = data.get("source_id")
    started_at = _parse_time(data.get("started_at"))
    if not isinstance(visit_id, str) or not isinstance(person_id, str):
        return None
    if not isinstance(source_id, str) or started_at is None:
        return None
    return VisitRow(visit_id, person_id, source_id, started_at, _parse_time(data.get("ended_at")))


def read_visits(paths: Iterable[Path]) -> list[VisitRow]:
    """Visits oldest first. A visit with only its start line is open; a visit
    whose start line was rotated away still shows up from its end line, which
    carries `started_at` too."""
    by_id: dict[str, VisitRow] = {}
    for event_type, data in _records(paths):
        if event_type not in (VISIT_STARTED, VISIT_ENDED):
            continue
        row = _row_from(data)
        if row is None:
            continue
        known = by_id.get(row.visit_id)
        if known is not None and known.ended_at is not None and row.ended_at is None:
            continue
        by_id[row.visit_id] = row
    return sorted(by_id.values(), key=lambda row: row.started_at)


def select_visits(
    rows: list[VisitRow], since: datetime | None = None, last: int | None = None
) -> list[VisitRow]:
    """Visits that started at or after `since`, then only the newest `last`."""
    selected = [row for row in rows if since is None or row.started_at >= since]
    if last is not None and last > 0:
        return selected[-last:]
    return selected


def read_labels(db_path: Path) -> dict[str, str]:
    """Names of the people in the presence database, read only. The runner may
    be using the file at the same time, so this never writes and never waits
    long. Any problem (no database yet, a locked file, a schema this version
    does not know) gives no names."""
    if not db_path.exists():
        return {}
    try:
        connection = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=_DB_TIMEOUT_S
        )
        try:
            found = connection.execute(
                "SELECT person_id, label FROM persons WHERE label IS NOT NULL"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        _log.warning("could not read names from %s, showing ids instead: %s", db_path, exc)
        return {}
    return {str(person_id): str(label) for person_id, label in found}


def format_dwell(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, _SECONDS_PER_HOUR)
    minutes, secs = divmod(rest, _SECONDS_PER_MINUTE)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _who(row: VisitRow, labels: Mapping[str, str]) -> str:
    return labels.get(row.person_id) or f"sin nombre ({row.person_id[:_SHORT_ID_CHARS]})"


def _clock(moment: datetime | None, tz: tzinfo | None) -> str:
    if moment is None:
        return _OPEN_VISIT
    return moment.astimezone(tz).strftime(_TIME_FORMAT)


def render_visits(
    rows: list[VisitRow], labels: Mapping[str, str], tz: tzinfo | None = None
) -> str:
    """A text table. Times are shown in `tz`, the machine's own zone by default."""
    if not rows:
        return _NO_VISITS
    lines = [f"{'Llegó':19}  {'Se fue':19}  {'Estancia':>8}  {'Fuente':10}  Persona"]
    for row in rows:
        dwell = format_dwell(row.dwell_s) if row.dwell_s is not None else "-"
        lines.append(
            f"{_clock(row.started_at, tz):19}  {_clock(row.ended_at, tz):19}  {dwell:>8}  "
            f"{row.source_id:10}  {_who(row, labels)}"
        )
    return "\n".join(lines)


def render_json(rows: list[VisitRow], labels: Mapping[str, str]) -> str:
    """One JSON array, one object per visit, for scripts."""
    payload = [
        {
            "visit_id": row.visit_id,
            "person_id": row.person_id,
            "label": labels.get(row.person_id),
            "source_id": row.source_id,
            "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at is not None else None,
            "dwell_s": row.dwell_s,
        }
        for row in rows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)
