"""Request handling of the local review page (SPEC.md ampliación, requisito 39).

`ReviewApp.handle()` turns a `Request` into a `Response` and knows nothing
about sockets, which keeps every security rule testable without a network.
`review_server.py` is the thin layer that speaks HTTP.

The page exposes photos and names of people, and it can change identities
(name, confirm, reject). Defences, in the order a request meets them:

1. **Host allow list.** Only the loopback names with the bound port are
   served. This is what stops DNS rebinding, where a hostile web page makes
   the browser talk to 127.0.0.1 under its own hostname.
2. **Login with the token file's secret**, exchanged for a session cookie
   (HttpOnly, SameSite=Strict). Everything except the stylesheet and the login
   page needs a live session.
3. **Same origin and CSRF token on every POST.** SameSite already blocks
   cross site cookies; the Origin check and the per session token are the
   second and third layer.
4. **Strict input handling.** Form bodies are size limited and must be
   urlencoded; ids must look like UUIDs (so nothing can name another path);
   names are length limited and must be printable text.
5. **Strict output.** Every response carries a Content-Security-Policy that
   allows nothing but this origin's stylesheet, one script file, images and
   background requests (no inline script, no eval), plus no-store, nosniff and
   no-referrer. Flash messages come from a fixed table.
6. **Audit trail.** Every change is reported to the `audit` sink with ids
   only, never names or photos.

Authorization is the token holder: a standalone runner has no Janus to ask
for `request_approval` or identity verification (requisito 36), so whoever
can log in is the owner. That is why the token file and loopback binding
matter.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from time import monotonic
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from janus_presence.errors import PresenceError
from janus_presence.review_auth import LoginThrottle, Session, SessionStore, token_matches
from janus_presence.review_pages import (
    APP_SCRIPT,
    STYLESHEET,
    PersonGroup,
    SourceRow,
    login_page,
    review_page,
)

__all__ = [
    "COOKIE_NAME",
    "MAX_BODY_BYTES",
    "AuditSink",
    "Request",
    "Response",
    "ReviewApp",
    "ReviewBackend",
    "allowed_hosts_for",
]

_log = logging.getLogger(__name__)

COOKIE_NAME = "janus_review"
MAX_BODY_BYTES = 4096
MAX_LABEL_CHARS = 64
MAX_ROLE_CHARS = 32
_ROLE_PATTERN = re.compile(rf"[a-z][a-z0-9_-]{{0,{MAX_ROLE_CHARS - 1}}}")
_MAX_FORM_FIELDS = 8
_MAX_QUERY_FIELDS = 4
_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ID_PATTERN = re.compile(_UUID)
_SNAPSHOT_PATH = re.compile(rf"/snapshot/({_UUID})")
_THUMB_PATH = re.compile(rf"/evidence/({_UUID})/thumb")
_CAMERA_PATH = re.compile(r"/camera/([A-Za-z0-9][A-Za-z0-9_.-]*)")
_STREAM_PATH = re.compile(r"/camera/([A-Za-z0-9][A-Za-z0-9_.-]*)/stream")
# The live view is a motion JPEG: one long response, one part per frame.
_STREAM_BOUNDARY = "janusframe"
_STREAM_INTERVAL_S = 0.125
_STREAM_RETRY_S = 0.25
_STREAM_IDLE_LIMIT_S = 30.0
_MAX_STREAMS = 4
_BULK_DECISIONS = frozenset({"confirm", "reject", "discard"})
# Same ceiling the settings form declares on its inputs.
_MAX_THRESHOLD = 4.0
_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
_HTTP_DEFAULT_PORT = 80
_OPAQUE_ORIGIN = "null"

_SECURITY_HEADERS = (
    (
        "Content-Security-Policy",
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    ),
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)

AuditSink = Callable[[str, Mapping[str, object]], None]


class ReviewBackend(Protocol):
    """What the page needs from the runner. Implementations take the service
    lock; the app never touches the service directly."""

    def review_groups(self) -> list[PersonGroup]: ...

    def sources(self) -> list[SourceRow]: ...

    def snapshot(self, person_id: str) -> bytes | None: ...

    def evidence_thumbnail(self, evidence_id: str) -> bytes | None: ...

    def camera_frame(self, source_id: str) -> bytes | None: ...

    def name_person(self, person_id: str, label: str) -> None: ...

    def set_role(self, person_id: str, role: str) -> None: ...

    def roles(self) -> tuple[str, ...]: ...

    def confirm_evidence(self, evidence_id: str) -> None: ...

    def reject_evidence(self, evidence_id: str) -> None: ...

    def discard_evidence(self, evidence_id: str) -> None: ...

    def resolve_all(self, person_id: str, decision: str) -> None: ...

    def merge_persons(self, source_id: str, target_id: str) -> None: ...

    def match_thresholds(self) -> tuple[float, float]: ...

    def set_match_thresholds(self, match: float, ambiguous: float) -> None: ...


@dataclass(frozen=True)
class Request:
    method: str
    target: str  # the raw request target: path and query
    headers: Mapping[str, str]  # header names in lower case
    body: bytes = b""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()
    # A body sent piece by piece for as long as the client stays (the live view).
    # When set, `body` is empty and no Content-Length is declared.
    stream: Iterable[bytes] | None = None


class _Reject(Exception):
    """Ends request handling early with a ready made response."""

    def __init__(self, response: Response) -> None:
        super().__init__(response.status)
        self.response = response


def allowed_hosts_for(port: int) -> frozenset[str]:
    """The Host header values the page answers to. Browsers leave the port out
    of the header when it is the HTTP default, so that form is accepted only
    for that port."""
    hosts = {f"{name}:{port}" for name in _LOOPBACK_NAMES}
    if port == _HTTP_DEFAULT_PORT:
        hosts.update(_LOOPBACK_NAMES)
    return frozenset(hosts)


def _plain(status: int, message: str) -> Response:
    return Response(status, message.encode("utf-8"), "text/plain; charset=utf-8")


def _redirect(location: str, headers: tuple[tuple[str, str], ...] = ()) -> Response:
    return Response(303, headers=(("Location", location), *headers))


def _page(status: int, markup: str, headers: tuple[tuple[str, str], ...] = ()) -> Response:
    return Response(status, markup.encode("utf-8"), headers=headers)


def _with_security_headers(response: Response) -> Response:
    return Response(
        response.status,
        response.body,
        response.content_type,
        (*response.headers, *_SECURITY_HEADERS),
        response.stream,
    )


def _valid_id(value: str | None) -> str | None:
    if value is not None and _ID_PATTERN.fullmatch(value):
        return value
    return None


def _return_anchor(fields: Mapping[str, str]) -> str:
    """Fragment that brings the browser back to the card a change came from, so a
    full page reload does not throw the owner to the top of a long page. Only a
    well formed id is echoed, which keeps anything else out of the Location."""
    person_id = _valid_id(fields.get("back"))
    return f"#p-{person_id}" if person_id is not None else ""


def _valid_label(value: str | None) -> str | None:
    if value is None:
        return None
    label = unicodedata.normalize("NFC", value).strip()
    if not label or len(label) > MAX_LABEL_CHARS or not label.isprintable():
        return None
    return label


def _valid_role(value: str | None) -> str | None:
    """A role is a short machine friendly word (`owner`, `family`): automations
    match it exactly, so it is kept lower case, with no spaces or accents."""
    if value is None:
        return None
    role = value.strip().lower()
    return role if _ROLE_PATTERN.fullmatch(role) else None


def _valid_threshold(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or not 0 < number <= _MAX_THRESHOLD:
        return None
    return number


def _image(data: bytes | None) -> Response:
    if data is None:
        return _plain(404, "No encontrado")
    return Response(200, data, "image/jpeg")


def _part(frame: bytes) -> bytes:
    header = (
        f"--{_STREAM_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n"
    )
    return header.encode("ascii") + frame + b"\r\n"


class _FrameStream:
    """The body of the live view: an iterator of multipart parts, one per frame,
    paced at `_STREAM_INTERVAL_S`. It ends when the app closes, when the camera
    gives nothing for `_STREAM_IDLE_LIMIT_S`, or when the transport calls
    `close()` (client gone). `close()` frees the stream slot exactly once, even
    if iteration never started."""

    def __init__(
        self,
        backend: ReviewBackend,
        source_id: str,
        closing: threading.Event,
        release: Callable[[], object],
    ) -> None:
        self._backend = backend
        self._source_id = source_id
        self._closing = closing
        self._release = release
        self._next_at = 0.0
        self._idle_since: float | None = None
        self._released = False

    def __iter__(self) -> _FrameStream:
        return self

    def __next__(self) -> bytes:
        while True:
            self._closing.wait(max(0.0, self._next_at - monotonic()))
            if self._closing.is_set():
                break
            frame = self._backend.camera_frame(self._source_id)
            self._next_at = monotonic() + _STREAM_INTERVAL_S
            if frame is not None:
                self._idle_since = None
                return _part(frame)
            if self._idle_for_too_long():
                break
            self._closing.wait(_STREAM_RETRY_S)
        self.close()
        raise StopIteration

    def _idle_for_too_long(self) -> bool:
        now = monotonic()
        if self._idle_since is None:
            self._idle_since = now
        return now - self._idle_since > _STREAM_IDLE_LIMIT_S

    def close(self) -> None:
        if not self._released:
            self._released = True
            self._release()


def _session_id(request: Request) -> str | None:
    raw = request.headers.get("cookie")
    if not raw:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel is not None else None


def _session_cookie(session_id: str, max_age_s: int) -> tuple[str, str]:
    return (
        "Set-Cookie",
        f"{COOKIE_NAME}={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age_s}",
    )


class ReviewApp:
    def __init__(
        self,
        backend: ReviewBackend,
        token: str,
        allowed_hosts: frozenset[str],
        audit: AuditSink | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not token:
            raise ValueError("the review app needs a non empty token")
        self._backend = backend
        self._token = token
        self._allowed_hosts = allowed_hosts
        self._audit = audit
        self._sessions = SessionStore(clock)
        self._throttle = LoginThrottle(clock)
        self._streams = threading.BoundedSemaphore(_MAX_STREAMS)
        self._closing = threading.Event()
        self._actions: dict[str, Callable[[Mapping[str, str]], str]] = {
            "/name": self._name,
            "/role": self._role,
            "/confirm": self._confirm,
            "/reject": self._reject,
            "/discard": self._discard,
            "/merge": self._merge,
            "/bulk": self._bulk,
            "/settings": self._settings,
        }

    def close(self) -> None:
        """Ends the live streams still open, so stopping the server does not wait
        for viewers to leave."""
        self._closing.set()

    def error(self, status: int, message: str) -> Response:
        """A plain error response that carries the same security headers as every
        other, for the transport layer to use when it rejects a request before
        `handle` ever sees it."""
        return _with_security_headers(_plain(status, message))

    def handle(self, request: Request) -> Response:
        try:
            response = self._dispatch(request)
        except _Reject as rejection:
            response = rejection.response
        except Exception:
            # The target can carry a query string, which stays out of the log.
            path = urlsplit(request.target).path
            _log.exception("review request failed: %s %s", request.method, path)
            response = _plain(500, "Error interno")
        return _with_security_headers(response)

    # -- routing -----------------------------------------------------------

    def _dispatch(self, request: Request) -> Response:
        self._require_allowed_host(request)
        if not request.target.startswith("/") or request.target.startswith("//"):
            raise _Reject(_plain(400, "Solicitud inválida"))
        url = urlsplit(request.target)
        route = (request.method, url.path)
        if route == ("GET", "/style.css"):
            return Response(200, STYLESHEET.encode("utf-8"), "text/css; charset=utf-8")
        if route == ("GET", "/app.js"):
            return Response(200, APP_SCRIPT.encode("utf-8"), "text/javascript; charset=utf-8")
        if route == ("GET", "/login"):
            return _page(200, login_page())
        if route == ("POST", "/login"):
            return self._login(request)
        return self._authenticated(request, url.path, url.query)

    def _authenticated(self, request: Request, path: str, query: str) -> Response:
        session_id = _session_id(request)
        session = self._sessions.lookup(session_id)
        if session is None:
            if request.method == "GET":
                return _redirect("/login")
            return _plain(403, "Sesión requerida")
        if request.method == "GET":
            return self._get(path, query, session)
        if request.method == "POST":
            return self._post(request, path, session, session_id)
        return _plain(405, "Método no permitido")

    def _get(self, path: str, query: str, session: Session) -> Response:
        if path == "/":
            return self._review(query, session)
        snapshot = _SNAPSHOT_PATH.fullmatch(path)
        if snapshot is not None:
            return _image(self._backend.snapshot(snapshot.group(1)))
        thumb = _THUMB_PATH.fullmatch(path)
        if thumb is not None:
            return _image(self._backend.evidence_thumbnail(thumb.group(1)))
        stream = _STREAM_PATH.fullmatch(path)
        if stream is not None:
            return self._stream(stream.group(1))
        camera = _CAMERA_PATH.fullmatch(path)
        if camera is not None:
            return _image(self._backend.camera_frame(camera.group(1)))
        return _plain(404, "No encontrado")

    def _post(
        self, request: Request, path: str, session: Session, session_id: str | None
    ) -> Response:
        self._require_same_origin(request)
        fields = self._read_form(request)
        if not token_matches(session.csrf, fields.get("csrf", "")):
            return _plain(403, "Token CSRF inválido")
        if path == "/logout":
            self._sessions.revoke(session_id)
            return _redirect("/login", (_session_cookie("", 0),))
        action = self._actions.get(path)
        if action is None:
            return _plain(404, "No encontrado")
        return _redirect(f"/?msg={action(fields)}{_return_anchor(fields)}")

    # -- pages -------------------------------------------------------------

    def _review(self, query: str, session: Session) -> Response:
        try:
            flash = parse_qs(query, max_num_fields=_MAX_QUERY_FIELDS).get("msg", [None])[0]
        except ValueError:
            flash = None
        markup = review_page(
            self._backend.review_groups(),
            self._backend.sources(),
            session.csrf,
            flash,
            self._backend.match_thresholds(),
            self._backend.roles(),
        )
        return _page(200, markup)

    def _stream(self, source_id: str) -> Response:
        if self._backend.camera_frame(source_id) is None:
            return _plain(404, "No encontrado")
        if not self._streams.acquire(blocking=False):
            return _plain(503, "Demasiadas transmisiones abiertas")
        body = _FrameStream(self._backend, source_id, self._closing, self._streams.release)
        content_type = f"multipart/x-mixed-replace; boundary={_STREAM_BOUNDARY}"
        return Response(200, content_type=content_type, stream=body)

    # -- login -------------------------------------------------------------

    def _login(self, request: Request) -> Response:
        self._require_same_origin(request)
        wait_s = self._throttle.retry_after_s()
        if wait_s > 0:
            markup = login_page("Demasiados intentos. Espera un momento.")
            return _page(429, markup, (("Retry-After", str(math.ceil(wait_s))),))
        fields = self._read_form(request)
        if not token_matches(self._token, fields.get("token", "")):
            self._throttle.record_failure()
            _log.warning("review login failed")
            return _page(401, login_page("Token incorrecto."))
        self._throttle.record_success()
        session_id, _ = self._sessions.create()
        _log.info("review login succeeded")
        cookie = _session_cookie(session_id, int(self._sessions.ttl_s))
        return _redirect("/", (cookie,))

    # -- actions (each returns the flash code) -------------------------------

    def _name(self, fields: Mapping[str, str]) -> str:
        person_id = _valid_id(fields.get("person_id"))
        label = _valid_label(fields.get("label"))
        if person_id is None or label is None:
            return "invalid"
        return self._run(
            "name_person",
            "named",
            {"person_id": person_id},
            lambda: self._backend.name_person(person_id, label),
        )

    def _role(self, fields: Mapping[str, str]) -> str:
        person_id = _valid_id(fields.get("person_id"))
        role = _valid_role(fields.get("role"))
        if person_id is None or role is None or role not in self._backend.roles():
            return "invalid"
        return self._run(
            "set_role",
            "role",
            {"person_id": person_id},
            lambda: self._backend.set_role(person_id, role),
        )

    def _confirm(self, fields: Mapping[str, str]) -> str:
        evidence_id = _valid_id(fields.get("evidence_id"))
        if evidence_id is None:
            return "invalid"
        return self._run(
            "confirm_evidence",
            "confirmed",
            {"evidence_id": evidence_id},
            lambda: self._backend.confirm_evidence(evidence_id),
        )

    def _reject(self, fields: Mapping[str, str]) -> str:
        evidence_id = _valid_id(fields.get("evidence_id"))
        if evidence_id is None:
            return "invalid"
        return self._run(
            "reject_evidence",
            "rejected",
            {"evidence_id": evidence_id},
            lambda: self._backend.reject_evidence(evidence_id),
        )

    def _discard(self, fields: Mapping[str, str]) -> str:
        evidence_id = _valid_id(fields.get("evidence_id"))
        if evidence_id is None:
            return "invalid"
        return self._run(
            "discard_evidence",
            "discarded",
            {"evidence_id": evidence_id},
            lambda: self._backend.discard_evidence(evidence_id),
        )

    def _merge(self, fields: Mapping[str, str]) -> str:
        source_id = _valid_id(fields.get("person_id"))
        target_id = _valid_id(fields.get("target_id"))
        if source_id is None or target_id is None or source_id == target_id:
            return "invalid"
        return self._run(
            "merge_persons",
            "merged",
            {"source_id": source_id, "target_id": target_id},
            lambda: self._backend.merge_persons(source_id, target_id),
        )

    def _bulk(self, fields: Mapping[str, str]) -> str:
        person_id = _valid_id(fields.get("person_id"))
        decision = fields.get("decision")
        if person_id is None or decision is None or decision not in _BULK_DECISIONS:
            return "invalid"
        return self._run(
            f"bulk_{decision}",
            f"bulk_{decision}",
            {"person_id": person_id},
            lambda: self._backend.resolve_all(person_id, decision),
        )

    def _settings(self, fields: Mapping[str, str]) -> str:
        match = _valid_threshold(fields.get("match_threshold"))
        ambiguous = _valid_threshold(fields.get("match_threshold_ambiguous"))
        if match is None or ambiguous is None or match >= ambiguous:
            return "invalid"
        return self._run(
            "set_match_thresholds",
            "settings",
            {"match": match, "ambiguous": ambiguous},
            lambda: self._backend.set_match_thresholds(match, ambiguous),
        )

    def _run(
        self,
        action: str,
        ok_code: str,
        subject: Mapping[str, object],
        call: Callable[[], None],
    ) -> str:
        """Runs one change and audits it. A refusal by the service (an
        unnamed person, evidence already settled) is an expected outcome, so it
        becomes a flash message; anything else is a bug and propagates."""
        try:
            call()
        except PresenceError as exc:
            _log.warning("review action %s refused: %s", action, exc)
            self._report(f"review_{action}_refused", subject)
            return "refused"
        self._report(f"review_{action}", subject)
        return ok_code

    def _report(self, event_type: str, subject: Mapping[str, object]) -> None:
        _log.info("%s %s", event_type, dict(subject))
        if self._audit is not None:
            self._audit(event_type, subject)

    # -- request checks --------------------------------------------------------

    def _require_allowed_host(self, request: Request) -> None:
        if request.headers.get("host", "").lower() not in self._allowed_hosts:
            raise _Reject(_plain(403, "Host no permitido"))

    def _require_same_origin(self, request: Request) -> None:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "").lower()
        fetch_site = request.headers.get("sec-fetch-site")
        if origin is not None and origin.lower() != f"http://{host}":
            if origin != _OPAQUE_ORIGIN or fetch_site != "same-origin":
                raise _Reject(_plain(403, "Origen no permitido"))
        if fetch_site is not None and fetch_site not in ("same-origin", "none"):
            raise _Reject(_plain(403, "Origen no permitido"))

    def _read_form(self, request: Request) -> dict[str, str]:
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != _FORM_CONTENT_TYPE:
            raise _Reject(_plain(415, "Tipo de contenido no soportado"))
        if len(request.body) > MAX_BODY_BYTES:
            raise _Reject(_plain(413, "Cuerpo demasiado grande"))
        try:
            parsed = parse_qs(
                request.body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=_MAX_FORM_FIELDS,
            )
        except (UnicodeDecodeError, ValueError):
            raise _Reject(_plain(400, "Formulario inválido")) from None
        return {name: values[0] for name, values in parsed.items()}
