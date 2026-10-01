"""Authentication for the local review page (SPEC.md ampliación, requisito 39,
and its security checklist: "interfaz de control del runner autenticada
(loopback, token en archivo 0600)").

The page shows photos and names of people, so it is treated as sensitive:

* **One secret, in a private file.** A 256 bit token is generated on first run
  and stored with `write_private` (0600 on POSIX, owner only ACL on Windows).
  A token file that turns out to be readable by other users is considered
  leaked and replaced, not trusted.
* **The token is typed once, never carried around.** Logging in trades it for a
  random session id in an HttpOnly, SameSite=Strict cookie. The token never
  appears in a URL, so it cannot end up in browser history or access logs.
* **Sessions are short lived and bounded.** They expire after an idle period,
  there are at most a handful at a time, and logging out revokes them.
* **Guessing is throttled.** Repeated failures lock logins for a while. The
  lock is global rather than per client because every client is loopback; it
  can lock the owner out for a minute, which is the accepted price.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from janus_platform.paths import PrivacyStatus, privacy_status, write_private

__all__ = [
    "LoginThrottle",
    "Session",
    "SessionStore",
    "load_or_create_token",
    "token_matches",
]

_log = logging.getLogger(__name__)

_TOKEN_BYTES = 32
_MIN_TOKEN_CHARS = 32
_SESSION_ID_BYTES = 32
_CSRF_BYTES = 32

DEFAULT_SESSION_TTL_S = 15 * 60
DEFAULT_MAX_SESSIONS = 8
DEFAULT_MAX_FAILURES = 5
DEFAULT_FAILURE_WINDOW_S = 300.0
DEFAULT_LOCKOUT_S = 60.0


def _create_token(path: Path) -> str:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    write_private(path, (token + "\n").encode("ascii"))
    return token


def load_or_create_token(path: Path) -> str:
    """The review token stored at `path`, creating the file if needed.

    A file readable by group or others is replaced with a fresh token, since
    whoever could read it can log in. An empty or too short file is replaced
    too: a weak secret is worse than a new one.
    """
    path = Path(path)
    if not path.exists():
        return _create_token(path)
    if privacy_status(path) == PrivacyStatus.OPEN:
        _log.warning(
            "review token file %s was readable by other users; issuing a new token", path
        )
        return _create_token(path)
    try:
        token = path.read_text(encoding="ascii").strip()
    except UnicodeDecodeError:
        token = ""
    if len(token) < _MIN_TOKEN_CHARS:
        _log.warning("review token file %s is empty or too short; issuing a new token", path)
        return _create_token(path)
    return token


def token_matches(expected: str, supplied: str) -> bool:
    """Constant time comparison, so response time does not leak how much of a
    guess was right."""
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


class LoginThrottle:
    """Locks logins after too many failures in a window. Thread safe."""

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        max_failures: int = DEFAULT_MAX_FAILURES,
        window_s: float = DEFAULT_FAILURE_WINDOW_S,
        lockout_s: float = DEFAULT_LOCKOUT_S,
    ) -> None:
        if max_failures < 1 or window_s <= 0 or lockout_s <= 0:
            raise ValueError("throttle needs max_failures >= 1 and positive window and lockout")
        self._clock = clock
        self._max_failures = max_failures
        self._window_s = window_s
        self._lockout_s = lockout_s
        self._failures: deque[float] = deque()
        self._locked_until = 0.0
        self._lock = threading.Lock()

    def retry_after_s(self) -> float:
        """Seconds until logins are allowed again; 0 when they are allowed now."""
        with self._lock:
            return max(0.0, self._locked_until - self._clock())

    def record_failure(self) -> None:
        with self._lock:
            now = self._clock()
            self._failures.append(now)
            while self._failures and now - self._failures[0] > self._window_s:
                self._failures.popleft()
            if len(self._failures) >= self._max_failures:
                self._locked_until = now + self._lockout_s
                self._failures.clear()
                _log.warning(
                    "review login locked for %.0fs after repeated failures", self._lockout_s
                )

    def record_success(self) -> None:
        with self._lock:
            self._failures.clear()


@dataclass
class Session:
    csrf: str
    expires_at: float


class SessionStore:
    """In memory sessions with a sliding idle expiry. Nothing is persisted, so
    restarting the runner logs everyone out, which is the desired behaviour."""

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        ttl_s: float = DEFAULT_SESSION_TTL_S,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        if ttl_s <= 0 or max_sessions < 1:
            raise ValueError("sessions need a positive ttl and room for at least one session")
        self._clock = clock
        self._ttl_s = ttl_s
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def ttl_s(self) -> float:
        return self._ttl_s

    def create(self) -> tuple[str, Session]:
        """A new session id (always fresh, never reused across logins) and its
        session. The oldest session is dropped when the store is full."""
        session_id = secrets.token_urlsafe(_SESSION_ID_BYTES)
        session = Session(
            csrf=secrets.token_urlsafe(_CSRF_BYTES), expires_at=self._clock() + self._ttl_s
        )
        with self._lock:
            self._drop_expired()
            while len(self._sessions) >= self._max_sessions:
                self._sessions.popitem(last=False)
            self._sessions[session_id] = session
        return session_id, session

    def lookup(self, session_id: str | None) -> Session | None:
        """The live session for this id, whose expiry moves forward; None if
        it is unknown or has expired."""
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            now = self._clock()
            if session.expires_at <= now:
                del self._sessions[session_id]
                return None
            session.expires_at = now + self._ttl_s
            self._sessions.move_to_end(session_id)
            return session

    def revoke(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def _drop_expired(self) -> None:
        now = self._clock()
        for session_id in [sid for sid, s in self._sessions.items() if s.expires_at <= now]:
            del self._sessions[session_id]
