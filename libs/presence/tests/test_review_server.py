"""ReviewServer (requisito 39): the HTTP transport, over a real loopback socket
on a port the system picks. What the server checks before a request is parsed
(Host, Content-Length) is tested here; the page's own rules are in
test_review_app.py."""

from __future__ import annotations

import http.client
from urllib.parse import urlencode

import pytest

from janus_presence.errors import PresenceError
from janus_presence.review_app import MAX_BODY_BYTES
from janus_presence.review_server import ReviewServer

TOKEN = "s" * 40
FORM = "application/x-www-form-urlencoded"
CONNECTION_TIMEOUT_S = 5


class EmptyBackend:
    def review_groups(self) -> list:
        return []

    def sources(self) -> list:
        return []

    def snapshot(self, person_id: str) -> bytes | None:
        return None

    def evidence_thumbnail(self, evidence_id: str) -> bytes | None:
        return None

    def camera_frame(self, source_id: str) -> bytes | None:
        return None

    def match_thresholds(self) -> tuple[float, float]:
        return (1.0, 1.3)

    def set_match_thresholds(self, match: float, ambiguous: float) -> None:
        return None

    def resolve_all(self, person_id: str, decision: str) -> None:
        return None

    def merge_persons(self, source_id: str, target_id: str) -> None:
        return None

    def name_person(self, person_id: str, label: str) -> None:
        return None

    def set_role(self, person_id: str, role: str) -> None:
        return None

    def roles(self) -> tuple[str, ...]:
        return ("owner",)

    def confirm_evidence(self, evidence_id: str) -> None:
        return None

    def reject_evidence(self, evidence_id: str) -> None:
        return None

    def discard_evidence(self, evidence_id: str) -> None:
        return None


@pytest.fixture
def server():
    review = ReviewServer(EmptyBackend(), TOKEN, "127.0.0.1", 0)
    review.start()
    yield review
    review.stop()


def connect(server: ReviewServer) -> http.client.HTTPConnection:
    return http.client.HTTPConnection("127.0.0.1", server.port, timeout=CONNECTION_TIMEOUT_S)


class TestBinding:
    def test_only_loopback_addresses_are_accepted(self):
        with pytest.raises(PresenceError, match="loopback"):
            ReviewServer(EmptyBackend(), TOKEN, "0.0.0.0", 0)

    def test_the_url_names_the_port_that_was_actually_bound(self, server):
        assert server.port != 0
        assert server.url == f"http://127.0.0.1:{server.port}/"

    def test_stopping_a_server_that_never_started_is_safe(self):
        ReviewServer(EmptyBackend(), TOKEN, "127.0.0.1", 0).stop()


class TestServing:
    def test_serves_the_login_page_with_the_security_headers(self, server):
        conn = connect(server)

        conn.request("GET", "/login")
        response = conn.getresponse()

        assert response.status == 200
        assert "Janus Presence" in response.read().decode("utf-8")
        assert "default-src 'none'" in response.getheader("Content-Security-Policy")

    def test_the_server_line_does_not_say_which_python_runs(self, server):
        conn = connect(server)

        conn.request("GET", "/login")
        response = conn.getresponse()

        assert response.getheader("Server").startswith("janus-review")
        assert "Python" not in response.getheader("Server")

    def test_logging_in_over_http_opens_the_review_page(self, server):
        conn = connect(server)
        conn.request(
            "POST",
            "/login",
            body=urlencode({"token": TOKEN}),
            headers={"Content-Type": FORM},
        )
        login = conn.getresponse()
        login.read()
        cookie = login.getheader("Set-Cookie").split(";")[0]

        page_conn = connect(server)
        page_conn.request("GET", "/", headers={"Cookie": cookie})
        page = page_conn.getresponse()

        assert login.status == 303
        assert page.status == 200
        assert "Revisión pendiente" in page.read().decode("utf-8")


class TestRefusedBeforeParsing:
    def test_a_host_that_is_not_the_bound_address_is_refused(self, server):
        conn = connect(server)

        conn.request("GET", "/login", headers={"Host": "evil.example"})

        assert conn.getresponse().status == 403

    def test_two_host_headers_are_refused(self, server):
        conn = connect(server)

        conn.putrequest("GET", "/login", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{server.port}")
        conn.putheader("Host", "evil.example")
        conn.endheaders()

        assert conn.getresponse().status == 400

    def test_a_post_without_a_declared_length_is_refused(self, server):
        conn = connect(server)

        conn.putrequest("POST", "/login")
        conn.putheader("Content-Type", FORM)
        conn.endheaders()

        assert conn.getresponse().status == 411

    def test_a_length_that_is_not_a_number_is_refused(self, server):
        conn = connect(server)

        conn.putrequest("POST", "/login")
        conn.putheader("Content-Type", FORM)
        conn.putheader("Content-Length", "abc")
        conn.endheaders()

        assert conn.getresponse().status == 400

    def test_a_declared_length_over_the_limit_is_refused_without_reading_the_body(self, server):
        conn = connect(server)

        conn.putrequest("POST", "/login")
        conn.putheader("Content-Type", FORM)
        conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
        conn.endheaders()

        assert conn.getresponse().status == 413
