"""Home Assistant sink for visit events (SPEC.md ampliación 2026-09-30,
requisito 42).

When someone's visit opens or closes, the runner tells Home Assistant (HA)
through its REST API: `POST /api/events/janus_presence`. HA automations then
decide what to do (turn a light on, log it, notify). `presence` only says who
was seen. It never decides an action and never authorizes anything
(requisito 25); an automation chained to this event must stay on harmless
actions such as lights, never locks or alarms (requisito 44).

Three rules shape it:

* **Seeing someone never waits for HA.** The service delivers visit events
  while it holds its lock, so the callback only builds a small payload and
  queues it. A worker thread does the HTTP call. If HA is slow or down, events
  are retried a few times and then dropped with a warning; if the queue fills
  up, the oldest event is discarded. Nothing here can raise into perception.
* **The token stays out of config and logs.** It is read from a file that must
  be private to the user, and only the URL is ever logged.
* **Standard library only.** One POST does not justify a new dependency.

The payload (event data in HA):

    {"kind": "visit_started" | "visit_ended", "visit_id", "person_id",
     "label", "role", "state", "source_id", "started_at", "last_seen_at",
     "at", "dwell_s" (only when ended)}

`label` and `role` are null for people who are still UNKNOWN.
"""

from __future__ import annotations

import http.client
import json
import logging
import queue
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from janus_platform.paths import PrivacyStatus, privacy_status

from janus_presence.errors import PresenceError
from janus_presence.models import IdentityState, PersonRecord, Visit

if TYPE_CHECKING:
    from janus_presence.service import PresenceService

__all__ = ["EVENT_TYPE", "HomeAssistantSink", "load_token", "post_event"]

_log = logging.getLogger(__name__)

EVENT_TYPE = "janus_presence"
VISIT_STARTED = "visit_started"
VISIT_ENDED = "visit_ended"

DEFAULT_TIMEOUT_S = 3.0
DEFAULT_QUEUE_SIZE = 100

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 1.0
_QUEUE_POLL_S = 0.5
_JOIN_TIMEOUT_S = 5.0

PostFunction = Callable[[str, str, dict[str, Any], float], None]


def load_token(path: Path) -> str:
    """The long lived access token HA issued, read from a private file.
    Failing here, at startup, beats discovering a missing token on the first
    visit."""
    path = Path(path)
    if not path.exists():
        raise PresenceError(
            f"The Home Assistant token file {path} does not exist. Create a long lived "
            "access token in your HA profile, save it there and restrict it to your user "
            "(chmod 600)."
        )
    if privacy_status(path) == PrivacyStatus.OPEN:
        raise PresenceError(
            f"The Home Assistant token file {path} is readable by other users. "
            "Restrict it to your user (chmod 600) and start again."
        )
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise PresenceError(f"The Home Assistant token file {path} is empty")
    return token


def post_event(url: str, token: str, payload: dict[str, Any], timeout_s: float) -> None:
    """Sends one event. Raises OSError (including HTTP errors) or
    http.client.HTTPException when HA cannot be reached or refuses it."""
    request = urllib.request.Request(  # noqa: S310 (scheme checked in the sink)
        f"{url.rstrip('/')}/api/events/{EVENT_TYPE}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        response.read()


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError(f"Home Assistant url must be http or https with a host, got '{url}'")
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        _log.warning(
            "Home Assistant url %s is plain http to a non loopback host: the token and the "
            "events travel unencrypted on the network",
            url,
        )


class HomeAssistantSink:
    def __init__(
        self,
        url: str,
        token: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_queue: int = DEFAULT_QUEUE_SIZE,
        post: PostFunction = post_event,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        if max_queue <= 0:
            raise ValueError("max_queue must be greater than zero")
        if not token:
            raise ValueError("token must not be empty")
        _check_url(url)
        self._url = url
        self._token = token
        self._timeout_s = timeout_s
        self._post = post
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lookup: Callable[[str], PersonRecord | None] | None = None

    def attach(self, service: PresenceService) -> None:
        """Subscribes to the service's visit events."""
        self._lookup = service.get_person
        service.on_visit_started(lambda visit: self._on_visit(VISIT_STARTED, visit))
        service.on_visit_ended(lambda visit: self._on_visit(VISIT_ENDED, visit))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="presence-home-assistant", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Safe to call on a sink that never started, and more than once.
        Events still queued are dropped."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=_JOIN_TIMEOUT_S)
        pending = self._queue.qsize()
        if pending:
            _log.warning("stopping with %d Home Assistant events not delivered", pending)

    def _on_visit(self, kind: str, visit: Visit) -> None:
        """Never raises: a failure here must not break the observation that
        triggered it."""
        try:
            self._enqueue(self._payload(kind, visit))
        except Exception:
            _log.exception("could not queue the %s event for Home Assistant", kind)

    def _payload(self, kind: str, visit: Visit) -> dict[str, Any]:
        person = self._lookup(visit.person_id) if self._lookup is not None else None
        known = person is not None and person.known
        payload: dict[str, Any] = {
            "kind": kind,
            "visit_id": visit.visit_id,
            "person_id": visit.person_id,
            "label": person.label if known and person is not None else None,
            "role": person.role if known and person is not None else None,
            "state": person.state.value if person is not None else IdentityState.UNKNOWN.value,
            "source_id": visit.source_id,
            "started_at": visit.started_at.isoformat(),
            "last_seen_at": visit.last_seen_at.isoformat(),
            "at": (visit.ended_at or visit.started_at).isoformat(),
        }
        if visit.ended_at is not None:
            payload["dwell_s"] = round((visit.ended_at - visit.started_at).total_seconds(), 3)
        return payload

    def _enqueue(self, payload: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(payload)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        _log.warning("Home Assistant event queue is full; dropped the oldest event")
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            _log.warning("Home Assistant event dropped, the queue stayed full")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=_QUEUE_POLL_S)
            except queue.Empty:
                continue
            self._deliver(payload)

    def _deliver(self, payload: dict[str, Any]) -> None:
        kind = payload["kind"]
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                self._post(self._url, self._token, payload, self._timeout_s)
                return
            except (OSError, http.client.HTTPException) as exc:
                _log.warning(
                    "Home Assistant %s event failed (attempt %d of %d) at %s: %s",
                    kind,
                    attempt,
                    _MAX_ATTEMPTS,
                    self._url,
                    exc,
                )
            if attempt == _MAX_ATTEMPTS:
                _log.warning("dropping the %s event for Home Assistant", kind)
                return
            if self._stop.wait(_BACKOFF_BASE_S * 2 ** (attempt - 1)):
                return
