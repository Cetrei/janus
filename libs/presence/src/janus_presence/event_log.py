"""Append only JSONL log of what the runner sees (SPEC.md ampliación,
requisito 39).

One JSON object per line: `{"ts": <UTC ISO 8601>, "type": ..., "data": {...}}`.
Two rules shape it:

* **Logging never breaks perception.** Seeing someone must not fail because
  the disk is full or the file is unwritable (SPEC.md Reliability), so a
  write error is logged once and the event dropped; `write` never raises.
* **Bounded size.** A runner on a Raspberry Pi cannot grow a file forever.
  When the file reaches `max_bytes` it is moved to `<name>.1` (replacing the
  previous backup) and a new one starts. Only one backup is kept.

The file holds ids and timestamps, never images or embeddings. It is still
created private (0600) because it says who was at home and when.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from janus_platform.paths import make_private

if TYPE_CHECKING:
    from janus_presence.models import Visit
    from janus_presence.service import PresenceService

_log = logging.getLogger(__name__)

PERSON_SEEN = "person_seen"
VISIT_STARTED = "visit_started"
VISIT_ENDED = "visit_ended"

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_SUFFIX = ".1"


def backup_path(path: Path) -> Path:
    """Where the log's one backup lives once the file reaches `max_bytes`."""
    return Path(path).with_name(Path(path).name + _BACKUP_SUFFIX)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


class JsonlEventLog:
    """Thread safe: several camera threads and the periodic jobs write to
    the same log."""

    def __init__(self, path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._handle: TextIO | None = None
        self._closed = False
        self._failing = False

    def write(self, event_type: str, data: Mapping[str, Any] | object) -> None:
        """Appends one event. `data` is a mapping or a dataclass instance.
        Never raises: an event that cannot be written or serialized is
        logged and dropped."""
        line = self._render(event_type, data)
        if line is None:
            return
        with self._lock:
            if not self._closed:
                self._append(line)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._drop_handle()

    def __enter__(self) -> JsonlEventLog:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @staticmethod
    def _render(event_type: str, data: Mapping[str, Any] | object) -> str | None:
        try:
            payload = data if isinstance(data, Mapping) else dataclasses.asdict(data)
            record = {"ts": datetime.now(UTC).isoformat(), "type": event_type, "data": payload}
            return json.dumps(record, default=_json_default, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            _log.warning("event %s not logged, cannot serialize it: %s", event_type, exc)
            return None

    def _append(self, line: str) -> None:
        try:
            handle = self._ensure_handle()
            handle.write(line + "\n")
            handle.flush()
        except OSError as exc:
            self._drop_handle()
            if not self._failing:
                _log.warning("event log %s is not writable: %s", self._path, exc)
            self._failing = True
            return
        self._failing = False

    def _ensure_handle(self) -> TextIO:
        handle = self._handle or self._open()
        if os.fstat(handle.fileno()).st_size < self._max_bytes:
            return handle
        self._drop_handle()
        os.replace(self._path, backup_path(self._path))
        return self._open()

    def _open(self) -> TextIO:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a", encoding="utf-8")
        make_private(self._path)
        return self._handle

    def _drop_handle(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        except OSError:
            _log.warning("event log %s did not close cleanly", self._path)
        self._handle = None


def _visit_payload(visit: Visit) -> dict[str, Any]:
    """A visit as logged. An ended visit also carries how long it lasted
    (requisito 30: `visit_ended` comes with the dwell time)."""
    payload = dataclasses.asdict(visit)
    if visit.ended_at is not None:
        payload["dwell_s"] = round((visit.ended_at - visit.started_at).total_seconds(), 3)
    return payload


def attach_event_log(
    service: PresenceService, log: JsonlEventLog, include_person_seen: bool = False
) -> None:
    """Wires the service's events into the log. `person_seen` is per frame
    and therefore optional; visit events are always logged."""
    service.on_visit_started(lambda visit: log.write(VISIT_STARTED, _visit_payload(visit)))
    service.on_visit_ended(lambda visit: log.write(VISIT_ENDED, _visit_payload(visit)))
    if include_person_seen:
        service.on_person_seen(lambda event: log.write(PERSON_SEEN, event))
