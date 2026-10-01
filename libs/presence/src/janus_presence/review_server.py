"""HTTP transport of the local review page (SPEC.md ampliación, requisito 39).

The standard library server is enough here: loopback only, one user, a handful
of routes, and no dependency to keep patched. All the policy lives in
`ReviewApp`; this module only moves bytes and enforces what has to happen
before a request is parsed at all:

* It refuses to bind anything but a loopback address, whatever the caller
  passes (the config validator already checks, this is the second lock).
* Each connection has a socket timeout, so a client that opens a connection
  and stalls (slowloris) cannot hold a thread for long.
* A POST declares its length up front and anything above the limit is refused
  without being read.
* One Host header, exactly. Two of them are how proxies and servers end up
  disagreeing about which host was asked for.
* The server line does not say which Python is running.
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from janus_presence.errors import PresenceError
from janus_presence.review_app import (
    MAX_BODY_BYTES,
    AuditSink,
    Request,
    Response,
    ReviewApp,
    ReviewBackend,
    allowed_hosts_for,
)

__all__ = ["ReviewServer"]

_log = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_CONNECTION_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.2
_STOP_TIMEOUT_S = 5.0


class _Handler(BaseHTTPRequestHandler):
    server_version = "janus-review"
    sys_version = ""
    timeout = _CONNECTION_TIMEOUT_S

    @property
    def app(self) -> ReviewApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        self._serve(b"")

    def do_POST(self) -> None:
        length = self._declared_length()
        if length is not None:
            self._serve(self.rfile.read(length))

    def _declared_length(self) -> int | None:
        """The declared body length, or None after answering with the reason it
        cannot be accepted."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            self._send(self.app.error(411, "Falta Content-Length"))
            return None
        if not raw.isdigit():
            self._send(self.app.error(400, "Content-Length inválido"))
            return None
        if int(raw) > MAX_BODY_BYTES:
            self._send(self.app.error(413, "Cuerpo demasiado grande"))
            return None
        return int(raw)

    def _serve(self, body: bytes) -> None:
        if len(self.headers.get_all("Host") or []) != 1:
            self._send(self.app.error(400, "Se requiere exactamente un encabezado Host"))
            return
        headers = {name.lower(): value for name, value in self.headers.items()}
        self._send(self.app.handle(Request(self.command, self.path, headers, body)))

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        if response.stream is None:
            self.send_header("Content-Length", str(len(response.body)))
        else:
            # No length to declare: the body lasts as long as the viewer stays.
            self.send_header("Connection", "close")
            self.close_connection = True
        for name, value in response.headers:
            self.send_header(name, value)
        self.end_headers()
        if response.stream is None:
            self.wfile.write(response.body)
            return
        self._send_stream(response.stream)

    def _send_stream(self, stream: Iterable[bytes]) -> None:
        """Writes each part as it comes. The viewer leaving is normal and ends the
        loop; the stream is always closed so its slot is freed."""
        try:
            for part in stream:
                self.wfile.write(part)
                self.wfile.flush()
        except OSError:
            _log.debug("review stream ended: the viewer disconnected")
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Kept at debug: the request line is enough to trace a problem and the
        # default handler writes to stderr for every request.
        _log.debug("review http %s", format % args)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    app: ReviewApp

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, handler)


class ReviewServer:
    """Serves the review page on a loopback address until stopped."""

    def __init__(
        self,
        backend: ReviewBackend,
        token: str,
        host: str,
        port: int,
        audit: AuditSink | None = None,
    ) -> None:
        if host not in _LOOPBACK_HOSTS:
            raise PresenceError(f"The review page only binds to loopback, not '{host}'")
        self._host = host
        self._httpd = _Server((host, port), _Handler)
        # Port 0 asks the system for a free one, so the allow list for the Host
        # header has to be built from the port that was actually bound.
        self._port = int(self._httpd.server_address[1])
        self._httpd.app = ReviewApp(backend, token, allowed_hosts_for(self._port), audit)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        host = f"[{self._host}]" if ":" in self._host else self._host
        return f"http://{host}:{self._port}/"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": _POLL_INTERVAL_S},
            name="presence-review",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        # Open live views would otherwise keep their threads writing.
        self._httpd.app.close()
        if self._thread is not None:
            self._httpd.shutdown()
            self._thread.join(timeout=_STOP_TIMEOUT_S)
            self._thread = None
        self._httpd.server_close()
