"""ReviewApp (requisito 39): the security rules of the review page, tested
without a socket. Time is a fake clock the test moves by hand, so session
expiry and login lockout need no sleeping."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from conftest import FakeClock

from janus_presence.errors import PresenceError
from janus_presence.review_app import (
    COOKIE_NAME,
    MAX_BODY_BYTES,
    Request,
    ReviewApp,
    allowed_hosts_for,
)
from janus_presence.review_auth import DEFAULT_MAX_SESSIONS, DEFAULT_SESSION_TTL_S
from janus_presence.review_pages import EvidenceItem, PersonGroup, SourceRow

PORT = 8765
HOST = f"127.0.0.1:{PORT}"
TOKEN = "t" * 40
PERSON_ID = "11111111-2222-3333-4444-555555555555"
OTHER_ID = "99999999-8888-7777-6666-555555555555"
EVIDENCE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FORM = "application/x-www-form-urlencoded"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
LOGIN_LOCKOUT_S = 60.0


class FakeBackend:
    """Records what the page asked for. `failure` makes every change raise."""

    def __init__(self) -> None:
        self.groups: list[PersonGroup] = []
        self.source_rows: list[SourceRow] = []
        self.snapshots: dict[str, bytes] = {}
        self.thumbnails: dict[str, bytes] = {}
        self.frames: dict[str, bytes] = {}
        self.thresholds: tuple[float, float] = (1.0, 1.3)
        self.vocabulary: tuple[str, ...] = ("owner", "family", "guest", "staff")
        self.calls: list[tuple] = []
        self.failure: Exception | None = None

    def review_groups(self) -> list[PersonGroup]:
        return self.groups

    def sources(self) -> list[SourceRow]:
        return self.source_rows

    def snapshot(self, person_id: str) -> bytes | None:
        return self.snapshots.get(person_id)

    def evidence_thumbnail(self, evidence_id: str) -> bytes | None:
        return self.thumbnails.get(evidence_id)

    def camera_frame(self, source_id: str) -> bytes | None:
        return self.frames.get(source_id)

    def match_thresholds(self) -> tuple[float, float]:
        return self.thresholds

    def name_person(self, person_id: str, label: str) -> None:
        self._change("name_person", person_id, label)

    def set_role(self, person_id: str, role: str) -> None:
        self._change("set_role", person_id, role)

    def roles(self) -> tuple[str, ...]:
        return self.vocabulary

    def confirm_evidence(self, evidence_id: str) -> None:
        self._change("confirm_evidence", evidence_id)

    def reject_evidence(self, evidence_id: str) -> None:
        self._change("reject_evidence", evidence_id)

    def discard_evidence(self, evidence_id: str) -> None:
        self._change("discard_evidence", evidence_id)

    def resolve_all(self, person_id: str, decision: str) -> None:
        self._change("resolve_all", person_id, decision)

    def merge_persons(self, source_id: str, target_id: str) -> None:
        self._change("merge_persons", source_id, target_id)

    def set_match_thresholds(self, match: float, ambiguous: float) -> None:
        self._change("set_match_thresholds", match, ambiguous)

    def _change(self, *call: object) -> None:
        if self.failure is not None:
            raise self.failure
        self.calls.append(call)


class Harness:
    def __init__(self) -> None:
        self.backend = FakeBackend()
        self.clock = FakeClock(1000.0)
        self.audit: list[tuple[str, dict]] = []
        self.app = ReviewApp(
            self.backend,
            TOKEN,
            allowed_hosts_for(PORT),
            audit=lambda event_type, subject: self.audit.append((event_type, dict(subject))),
            clock=self.clock,
        )


def get(app: ReviewApp, target: str, cookie: str | None = None, host: str = HOST):
    headers = {"host": host}
    if cookie is not None:
        headers["cookie"] = f"{COOKIE_NAME}={cookie}"
    return app.handle(Request("GET", target, headers))


def raw_post(
    app: ReviewApp,
    target: str,
    body: bytes,
    cookie: str | None = None,
    headers: dict[str, str] | None = None,
):
    merged = {"host": HOST, "content-type": FORM}
    if cookie is not None:
        merged["cookie"] = f"{COOKIE_NAME}={cookie}"
    merged.update(headers or {})
    return app.handle(Request("POST", target, merged, body))


def post(
    app: ReviewApp,
    target: str,
    fields: dict[str, str],
    cookie: str | None = None,
    headers: dict[str, str] | None = None,
):
    return raw_post(app, target, urlencode(fields).encode(), cookie, headers)


def header(response, name: str) -> str | None:
    for key, value in response.headers:
        if key.lower() == name.lower():
            return value
    return None


def body_of(response) -> str:
    return response.body.decode("utf-8")


def log_in(app: ReviewApp) -> str:
    response = post(app, "/login", {"token": TOKEN})
    assert response.status == 303
    return header(response, "Set-Cookie").split(";")[0].split("=", 1)[1]


def csrf_of(app: ReviewApp, cookie: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', body_of(get(app, "/", cookie)))
    assert match is not None
    return match.group(1)


def make_group(
    label: str | None = "Ana",
    state: str = "provisional",
    has_snapshot: bool = True,
    role: str | None = None,
) -> PersonGroup:
    item = EvidenceItem(
        EVIDENCE_ID, NOW, "cuarto", hypothesis_label="Beto", hypothesis_confidence=0.55
    )
    return PersonGroup(PERSON_ID, label, state, role, has_snapshot, NOW, NOW, (item,))


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def signed_in(harness: Harness) -> SimpleNamespace:
    cookie = log_in(harness.app)
    return SimpleNamespace(cookie=cookie, csrf=csrf_of(harness.app, cookie))


def act(harness: Harness, signed_in: SimpleNamespace, path: str, **fields: str):
    fields = {"csrf": signed_in.csrf, **fields}
    return post(harness.app, path, fields, signed_in.cookie)


class TestRequestShape:
    def test_a_host_that_is_not_loopback_is_refused(self, harness):
        assert get(harness.app, "/login", host="evil.example:8765").status == 403

    def test_a_loopback_host_on_another_port_is_refused(self, harness):
        assert get(harness.app, "/login", host="127.0.0.1:9999").status == 403

    def test_a_host_without_the_port_is_refused_when_the_port_is_not_80(self, harness):
        assert get(harness.app, "/login", host="127.0.0.1").status == 403

    def test_the_host_is_compared_ignoring_case(self, harness):
        assert get(harness.app, "/login", host="LOCALHOST:8765").status == 200

    def test_a_post_from_a_foreign_host_is_refused_too(self, harness):
        response = post(harness.app, "/login", {"token": TOKEN}, headers={"host": "evil:8765"})

        assert response.status == 403

    @pytest.mark.parametrize("target", ["//evil.example/x", "http://evil.example/", "login"])
    def test_a_target_that_is_not_a_plain_path_is_refused(self, harness, target):
        assert get(harness.app, target).status == 400


class TestSecurityHeaders:
    def test_every_kind_of_response_carries_them(self, harness):
        responses = [
            get(harness.app, "/login"),
            get(harness.app, "/style.css"),
            get(harness.app, "/"),
            get(harness.app, "/login", host="evil"),
            harness.app.error(413, "too big"),
        ]

        for response in responses:
            assert "default-src 'none'" in header(response, "Content-Security-Policy")
            assert header(response, "Cache-Control") == "no-store"
            assert header(response, "X-Content-Type-Options") == "nosniff"
            assert header(response, "X-Frame-Options") == "DENY"


class TestLogin:
    def test_the_login_page_and_stylesheet_need_no_session(self, harness):
        login = get(harness.app, "/login")
        style = get(harness.app, "/style.css")

        assert login.status == 200
        assert style.status == 200
        assert style.content_type.startswith("text/css")

    def test_the_right_token_starts_a_session_in_a_strict_httponly_cookie(self, harness):
        response = post(harness.app, "/login", {"token": TOKEN})

        cookie = header(response, "Set-Cookie")
        assert response.status == 303
        assert header(response, "Location") == "/"
        assert cookie.startswith(f"{COOKIE_NAME}=")
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie

    def test_the_token_is_never_echoed_back(self, harness):
        response = post(harness.app, "/login", {"token": TOKEN})

        assert TOKEN not in str(response.headers)
        assert TOKEN not in body_of(response)

    def test_a_wrong_token_is_refused_without_a_cookie(self, harness):
        response = post(harness.app, "/login", {"token": "nope"})

        assert response.status == 401
        assert header(response, "Set-Cookie") is None

    def test_every_login_gets_a_fresh_session_id(self, harness):
        assert log_in(harness.app) != log_in(harness.app)

    def test_repeated_failures_lock_logins_even_for_the_right_token(self, harness):
        for _ in range(5):
            post(harness.app, "/login", {"token": "nope"})

        locked = post(harness.app, "/login", {"token": TOKEN})

        assert locked.status == 429
        assert int(header(locked, "Retry-After")) > 0

    def test_logins_work_again_after_the_lockout(self, harness):
        for _ in range(5):
            post(harness.app, "/login", {"token": "nope"})
        harness.clock.now += LOGIN_LOCKOUT_S + 1

        assert post(harness.app, "/login", {"token": TOKEN}).status == 303

    def test_a_login_from_another_origin_is_refused(self, harness):
        response = post(
            harness.app, "/login", {"token": TOKEN}, headers={"origin": "http://evil.example"}
        )

        assert response.status == 403

    def test_a_login_from_the_same_origin_is_accepted(self, harness):
        response = post(
            harness.app, "/login", {"token": TOKEN}, headers={"origin": f"http://{HOST}"}
        )

        assert response.status == 303

    def test_a_cross_site_fetch_is_refused(self, harness):
        response = post(
            harness.app, "/login", {"token": TOKEN}, headers={"sec-fetch-site": "cross-site"}
        )

        assert response.status == 403


class TestSessions:
    def test_an_opaque_origin_is_accepted_when_the_browser_says_same_origin(self, harness):
        response = post(
            harness.app,
            "/login",
            {"token": TOKEN},
            headers={"origin": "null", "sec-fetch-site": "same-origin"},
        )

        assert response.status == 303

    def test_an_opaque_origin_without_fetch_metadata_is_refused(self, harness):
        response = post(harness.app, "/login", {"token": TOKEN}, headers={"origin": "null"})

        assert response.status == 403

    def test_an_opaque_origin_from_a_cross_site_request_is_refused(self, harness):
        response = post(
            harness.app,
            "/login",
            {"token": TOKEN},
            headers={"origin": "null", "sec-fetch-site": "cross-site"},
        )

        assert response.status == 403


class TestSessionsLifecycle:
    def test_a_page_without_a_session_redirects_to_the_login(self, harness):
        response = get(harness.app, "/")

        assert response.status == 303
        assert header(response, "Location") == "/login"

    def test_an_unknown_cookie_is_no_session(self, harness):
        assert get(harness.app, "/", cookie="made-up").status == 303

    def test_a_change_without_a_session_is_refused(self, harness):
        response = post(harness.app, "/name", {"person_id": PERSON_ID, "label": "Ana"})

        assert response.status == 403
        assert harness.backend.calls == []

    def test_a_session_expires_after_being_idle(self, harness, signed_in):
        harness.clock.now += DEFAULT_SESSION_TTL_S + 1

        assert get(harness.app, "/", signed_in.cookie).status == 303

    def test_using_a_session_keeps_it_alive(self, harness, signed_in):
        step = DEFAULT_SESSION_TTL_S * 0.8

        harness.clock.now += step
        assert get(harness.app, "/", signed_in.cookie).status == 200
        harness.clock.now += step
        assert get(harness.app, "/", signed_in.cookie).status == 200

    def test_logout_revokes_the_session_and_clears_the_cookie(self, harness, signed_in):
        response = act(harness, signed_in, "/logout")

        assert response.status == 303
        assert "Max-Age=0" in header(response, "Set-Cookie")
        assert get(harness.app, "/", signed_in.cookie).status == 303

    def test_the_oldest_session_is_dropped_when_too_many_are_open(self, harness):
        cookies = [log_in(harness.app) for _ in range(DEFAULT_MAX_SESSIONS + 1)]

        assert get(harness.app, "/", cookies[0]).status == 303
        assert get(harness.app, "/", cookies[-1]).status == 200

    def test_only_get_and_post_are_served(self, harness, signed_in):
        request = Request("PUT", "/", {"host": HOST, "cookie": f"{COOKIE_NAME}={signed_in.cookie}"})

        assert harness.app.handle(request).status == 405


class TestPostProtections:
    def test_a_change_without_the_csrf_token_is_refused(self, harness, signed_in):
        fields = {"person_id": PERSON_ID, "label": "Ana"}

        response = post(harness.app, "/name", fields, signed_in.cookie)

        assert response.status == 403
        assert harness.backend.calls == []

    def test_a_change_with_the_wrong_csrf_token_is_refused(self, harness, signed_in):
        fields = {"csrf": "wrong", "person_id": PERSON_ID, "label": "Ana"}

        assert post(harness.app, "/name", fields, signed_in.cookie).status == 403

    def test_a_change_from_another_origin_is_refused_even_with_a_valid_token(
        self, harness, signed_in
    ):
        fields = {"csrf": signed_in.csrf, "person_id": PERSON_ID, "label": "Ana"}

        response = post(
            harness.app, "/name", fields, signed_in.cookie, {"origin": "http://evil.example"}
        )

        assert response.status == 403
        assert harness.backend.calls == []

    def test_a_body_that_is_not_a_form_is_refused(self, harness, signed_in):
        response = raw_post(
            harness.app, "/name", b"{}", signed_in.cookie, {"content-type": "application/json"}
        )

        assert response.status == 415

    def test_a_body_over_the_limit_is_refused(self, harness, signed_in):
        response = raw_post(harness.app, "/name", b"x" * (MAX_BODY_BYTES + 1), signed_in.cookie)

        assert response.status == 413

    def test_a_body_that_is_not_utf8_is_refused(self, harness, signed_in):
        assert raw_post(harness.app, "/name", b"\xff\xfe", signed_in.cookie).status == 400

    def test_a_form_with_too_many_fields_is_refused(self, harness, signed_in):
        fields = {f"f{index}": "x" for index in range(20)}

        assert post(harness.app, "/name", fields, signed_in.cookie).status == 400

    def test_an_unknown_action_is_not_found(self, harness, signed_in):
        assert act(harness, signed_in, "/erase-everything").status == 404


class TestActions:
    def test_naming_a_person_calls_the_backend_and_flashes_success(self, harness, signed_in):
        response = act(harness, signed_in, "/name", person_id=PERSON_ID, label="  Ana  ")

        assert header(response, "Location") == "/?msg=named"
        assert harness.backend.calls == [("name_person", PERSON_ID, "Ana")]

    def test_the_name_is_normalized_to_nfc(self, harness, signed_in):
        act(harness, signed_in, "/name", person_id=PERSON_ID, label="Jose\u0301")

        assert harness.backend.calls == [("name_person", PERSON_ID, "Jos\u00e9")]

    def test_a_name_of_the_maximum_length_is_accepted(self, harness, signed_in):
        act(harness, signed_in, "/name", person_id=PERSON_ID, label="x" * 64)

        assert len(harness.backend.calls) == 1

    @pytest.mark.parametrize("label", ["", "   ", "x" * 65, "line\nbreak"])
    def test_a_name_that_is_empty_too_long_or_not_printable_is_invalid(
        self, harness, signed_in, label
    ):
        response = act(harness, signed_in, "/name", person_id=PERSON_ID, label=label)

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []

    @pytest.mark.parametrize("person_id", ["../etc/passwd", "1234", "", PERSON_ID + "0"])
    def test_an_id_that_is_not_a_uuid_is_invalid(self, harness, signed_in, person_id):
        response = act(harness, signed_in, "/name", person_id=person_id, label="Ana")

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []

    @pytest.mark.parametrize(
        ("path", "call", "flash", "audit"),
        [
            ("/confirm", "confirm_evidence", "confirmed", "review_confirm_evidence"),
            ("/reject", "reject_evidence", "rejected", "review_reject_evidence"),
            ("/discard", "discard_evidence", "discarded", "review_discard_evidence"),
        ],
    )
    def test_evidence_actions_call_the_backend_and_are_audited(
        self, harness, signed_in, path, call, flash, audit
    ):
        response = act(harness, signed_in, path, evidence_id=EVIDENCE_ID)

        assert header(response, "Location") == f"/?msg={flash}"
        assert harness.backend.calls == [(call, EVIDENCE_ID)]
        assert harness.audit == [(audit, {"evidence_id": EVIDENCE_ID})]

    def test_the_audit_trail_holds_ids_and_never_the_name(self, harness, signed_in):
        act(harness, signed_in, "/name", person_id=PERSON_ID, label="Ana")

        assert harness.audit == [("review_name_person", {"person_id": PERSON_ID})]

    def test_a_refusal_by_the_service_becomes_a_flash_message_and_is_audited(
        self, harness, signed_in
    ):
        harness.backend.failure = PresenceError("person has no name")

        response = act(harness, signed_in, "/confirm", evidence_id=EVIDENCE_ID)

        assert header(response, "Location") == "/?msg=refused"
        assert harness.audit == [("review_confirm_evidence_refused", {"evidence_id": EVIDENCE_ID})]

    def test_an_unexpected_failure_is_a_500_without_details(self, harness, signed_in):
        harness.backend.failure = RuntimeError("secret detail")

        response = act(harness, signed_in, "/confirm", evidence_id=EVIDENCE_ID)

        assert response.status == 500
        assert "secret detail" not in body_of(response)


class TestPages:
    def test_an_empty_review_says_there_is_nothing_pending(self, harness, signed_in):
        response = get(harness.app, "/", signed_in.cookie)

        assert response.status == 200
        assert "No hay nada pendiente" in body_of(response)

    def test_a_pending_person_shows_the_photo_the_evidence_and_the_guess(self, harness, signed_in):
        harness.backend.groups = [make_group()]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert f'src="/snapshot/{PERSON_ID}"' in body
        assert "Ana" in body
        assert "Podría ser Beto" in body
        assert 'action="/confirm"' in body

    def test_a_person_without_a_photo_says_so(self, harness, signed_in):
        harness.backend.groups = [make_group(has_snapshot=False)]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert "/snapshot/" not in body
        assert "Sin foto" in body

    def test_confirming_is_disabled_until_the_person_has_a_name(self, harness, signed_in):
        harness.backend.groups = [make_group(label=None, state="unknown")]

        assert " disabled" in body_of(get(harness.app, "/", signed_in.cookie))

    def test_confirming_is_enabled_for_a_named_person(self, harness, signed_in):
        harness.backend.groups = [make_group()]

        assert " disabled" not in body_of(get(harness.app, "/", signed_in.cookie))

    def test_values_from_the_database_are_escaped(self, harness, signed_in):
        group = make_group(label="<script>alert(1)</script>")
        hostile = EvidenceItem(EVIDENCE_ID, NOW, "cuarto", '"><img src=x onerror=alert(1)>', 0.5)
        harness.backend.groups = [
            PersonGroup(PERSON_ID, group.label, "provisional", None, True, NOW, NOW, (hostile,))
        ]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert "<script>" not in body
        assert "<img src=x" not in body
        assert "&lt;script&gt;" in body

    def test_a_known_flash_code_shows_its_fixed_message(self, harness, signed_in):
        body = body_of(get(harness.app, "/?msg=named", signed_in.cookie))

        assert "Nombre guardado." in body

    def test_an_unknown_flash_code_shows_nothing(self, harness, signed_in):
        body = body_of(get(harness.app, "/?msg=<b>hi</b>", signed_in.cookie))

        assert "<b>hi</b>" not in body
        assert 'role="status"' not in body

    def test_a_query_with_too_many_fields_is_ignored_not_an_error(self, harness, signed_in):
        response = get(harness.app, "/?msg=named&a=1&b=2&c=3&d=4&e=5", signed_in.cookie)

        assert response.status == 200
        assert 'role="status"' not in body_of(response)

    def test_a_source_that_is_down_shows_its_state_and_an_escaped_error(self, harness, signed_in):
        harness.backend.source_rows = [SourceRow("cuarto", "down", None, 3, 0, "<b>boom</b>")]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert "Caída" in body
        assert "nunca" in body
        assert "<b>boom</b>" not in body

    def test_a_long_error_is_cut(self, harness, signed_in):
        harness.backend.source_rows = [SourceRow("cuarto", "down", None, 1, 0, "e" * 300)]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert "e" * 200 in body
        assert "e" * 201 not in body


class TestSnapshot:
    def test_a_retained_photo_is_served_as_a_jpeg(self, harness, signed_in):
        harness.backend.snapshots[PERSON_ID] = b"\xff\xd8jpeg"

        response = get(harness.app, f"/snapshot/{PERSON_ID}", signed_in.cookie)

        assert response.status == 200
        assert response.content_type == "image/jpeg"
        assert response.body == b"\xff\xd8jpeg"

    def test_a_person_without_a_photo_is_not_found(self, harness, signed_in):
        assert get(harness.app, f"/snapshot/{PERSON_ID}", signed_in.cookie).status == 404

    @pytest.mark.parametrize("path", ["/snapshot/..%2f..%2fetc", "/snapshot/1234", "/snapshot/"])
    def test_a_path_that_is_not_a_person_id_is_not_found(self, harness, signed_in, path):
        assert get(harness.app, path, signed_in.cookie).status == 404

    def test_a_photo_is_never_served_without_a_session(self, harness):
        harness.backend.snapshots[PERSON_ID] = b"\xff\xd8jpeg"

        response = get(harness.app, f"/snapshot/{PERSON_ID}")

        assert response.status == 303
        assert response.body == b""


class TestReturnAnchor:
    def test_a_change_returns_to_the_card_it_came_from(self, harness, signed_in):
        response = act(harness, signed_in, "/confirm", evidence_id=EVIDENCE_ID, back=PERSON_ID)

        assert header(response, "Location") == f"/?msg=confirmed#p-{PERSON_ID}"

    @pytest.mark.parametrize("back", ["", "../x", "x\r\nSet-Cookie: a=b", PERSON_ID + "0"])
    def test_an_anchor_that_is_not_a_uuid_is_ignored(self, harness, signed_in, back):
        response = act(harness, signed_in, "/confirm", evidence_id=EVIDENCE_ID, back=back)

        assert header(response, "Location") == "/?msg=confirmed"

    def test_each_card_has_an_anchor_and_its_forms_point_back_to_it(self, harness, signed_in):
        harness.backend.groups = [make_group()]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert f'id="p-{PERSON_ID}"' in body
        assert f'name="back" value="{PERSON_ID}"' in body


class TestReviewReadability:
    def test_only_the_newest_rows_stay_open_and_the_rest_fold_away(self, harness, signed_in):
        items = tuple(
            EvidenceItem(f"{index:08x}-bbbb-cccc-dddd-eeeeeeeeeeee", NOW, "cuarto")
            for index in range(9)
        )
        harness.backend.groups = [
            PersonGroup(PERSON_ID, "Ana", "provisional", None, False, NOW, NOW, items)
        ]

        body = body_of(get(harness.app, "/", signed_in.cookie))
        folded = body.split("<details", 1)[1]

        assert "Ver 4 más antiguas" in body
        assert body.count('action="/confirm"') == 9
        assert folded.count('action="/confirm"') == 4

    def test_a_named_person_without_a_photo_is_told_it_was_deleted_on_naming(
        self, harness, signed_in
    ):
        harness.backend.groups = [make_group(has_snapshot=False)]

        assert "Se borra al ponerle nombre" in body_of(get(harness.app, "/", signed_in.cookie))

    def test_an_unnamed_person_without_a_photo_is_told_none_was_kept(self, harness, signed_in):
        harness.backend.groups = [make_group(label=None, state="unknown", has_snapshot=False)]

        assert "No se guardó" in body_of(get(harness.app, "/", signed_in.cookie))

    @pytest.mark.parametrize(
        ("confidence", "band"),
        [(0.0, "parecido bajo"), (0.4, "parecido medio"), (0.8, "parecido alto")],
    )
    def test_a_guess_shows_a_similarity_band_and_keeps_the_number_in_a_tooltip(
        self, harness, signed_in, confidence, band
    ):
        item = EvidenceItem(EVIDENCE_ID, NOW, "cuarto", "Beto", confidence)
        harness.backend.groups = [
            PersonGroup(PERSON_ID, "Ana", "provisional", None, True, NOW, NOW, (item,))
        ]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert band in body
        assert f'title="confianza {confidence:.2f}"' in body


class TestScriptAndThumbnails:
    def test_the_script_is_served_without_a_session_from_the_same_origin(self, harness):
        response = get(harness.app, "/app.js")

        assert response.status == 200
        assert response.content_type.startswith("text/javascript")

    def test_the_policy_allows_only_this_origins_script_and_requests(self, harness):
        policy = header(get(harness.app, "/login"), "Content-Security-Policy")

        assert "script-src 'self'" in policy
        assert "connect-src 'self'" in policy
        assert "unsafe-inline" not in policy

    def test_the_review_page_loads_the_script_and_has_no_inline_script(self, harness, signed_in):
        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert '<script src="/app.js" defer></script>' in body
        assert body.count("<script") == 1

    def test_a_thumbnail_is_served_as_a_jpeg(self, harness, signed_in):
        harness.backend.thumbnails[EVIDENCE_ID] = b"\xff\xd8thumb"

        response = get(harness.app, f"/evidence/{EVIDENCE_ID}/thumb", signed_in.cookie)

        assert response.status == 200
        assert response.content_type == "image/jpeg"
        assert response.body == b"\xff\xd8thumb"

    def test_evidence_without_a_thumbnail_is_not_found(self, harness, signed_in):
        assert get(harness.app, f"/evidence/{EVIDENCE_ID}/thumb", signed_in.cookie).status == 404

    def test_a_thumbnail_is_never_served_without_a_session(self, harness):
        harness.backend.thumbnails[EVIDENCE_ID] = b"\xff\xd8thumb"

        response = get(harness.app, f"/evidence/{EVIDENCE_ID}/thumb")

        assert response.status == 303
        assert response.body == b""

    def test_a_row_with_a_thumbnail_shows_it(self, harness, signed_in):
        item = EvidenceItem(EVIDENCE_ID, NOW, "cuarto", has_thumb=True)
        harness.backend.groups = [
            PersonGroup(PERSON_ID, "Ana", "provisional", None, False, NOW, NOW, (item,))
        ]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert f'src="/evidence/{EVIDENCE_ID}/thumb"' in body


def open_streams_until_refused(app: ReviewApp, cookie: str, limit: int = 32):
    """Opens live streams of 'cuarto' until the app refuses one. Returns the open
    responses and the refusal, so a test does not hard code how many fit."""
    opened = []
    for _ in range(limit):
        response = get(app, "/camera/cuarto/stream", cookie)
        if response.status != 200:
            return opened, response
        opened.append(response)
    raise AssertionError("streams were never refused")


class TestLiveCamera:
    def test_the_newest_frame_is_served_as_a_jpeg(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"\xff\xd8frame"

        response = get(harness.app, "/camera/cuarto", signed_in.cookie)

        assert response.status == 200
        assert response.content_type == "image/jpeg"
        assert response.body == b"\xff\xd8frame"

    def test_a_camera_without_a_frame_is_not_found(self, harness, signed_in):
        assert get(harness.app, "/camera/cuarto", signed_in.cookie).status == 404

    def test_the_live_view_is_never_served_without_a_session(self, harness):
        harness.backend.frames["cuarto"] = b"\xff\xd8frame"

        response = get(harness.app, "/camera/cuarto")

        assert response.status == 303
        assert response.body == b""

    @pytest.mark.parametrize("path", ["/camera/", "/camera/..%2fetc", "/camera/a/b", "/camera/-x"])
    def test_a_path_that_is_not_a_source_id_is_not_found(self, harness, signed_in, path):
        assert get(harness.app, path, signed_in.cookie).status == 404

    def test_a_source_that_is_up_shows_its_live_view(self, harness, signed_in):
        harness.backend.source_rows = [SourceRow("cuarto", "up", NOW, 0, 0, None)]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert 'src="/camera/cuarto/stream"' in body

    def test_a_source_that_is_down_shows_no_live_view(self, harness, signed_in):
        harness.backend.source_rows = [SourceRow("cuarto", "down", None, 2, 0, "x")]

        assert "/camera/" not in body_of(get(harness.app, "/", signed_in.cookie))


class TestRole:
    def test_a_role_is_saved_lower_cased_and_audited_by_id_only(self, harness, signed_in):
        response = act(harness, signed_in, "/role", person_id=PERSON_ID, role="  Owner ")

        assert header(response, "Location") == "/?msg=role"
        assert harness.backend.calls == [("set_role", PERSON_ID, "owner")]
        assert harness.audit == [("review_set_role", {"person_id": PERSON_ID})]

    @pytest.mark.parametrize(
        "role",
        ["", "   ", "two words", "1abc", "dueño", "a" * 33, "own<er>", "-owner", "onwer", "admin"],
    )
    def test_a_role_that_is_not_in_the_vocabulary_is_refused(self, harness, signed_in, role):
        response = act(harness, signed_in, "/role", person_id=PERSON_ID, role=role)

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []

    def test_any_role_of_the_configured_vocabulary_is_accepted(self, harness, signed_in):
        harness.backend.vocabulary = ("a" * 32,)

        response = act(harness, signed_in, "/role", person_id=PERSON_ID, role="a" * 32)

        assert header(response, "Location") == "/?msg=role"

    def test_a_role_needs_a_well_formed_person_id(self, harness, signed_in):
        response = act(harness, signed_in, "/role", person_id="../etc", role="owner")

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []

    def test_a_refusal_by_the_service_is_a_message_not_an_error(self, harness, signed_in):
        harness.backend.failure = PresenceError("gone")

        response = act(harness, signed_in, "/role", person_id=PERSON_ID, role="owner")

        assert header(response, "Location") == "/?msg=refused"
        assert harness.audit == [("review_set_role_refused", {"person_id": PERSON_ID})]

    def test_setting_a_role_needs_the_csrf_token(self, harness, signed_in):
        response = post(
            harness.app,
            "/role",
            {"person_id": PERSON_ID, "role": "owner", "csrf": "wrong"},
            signed_in.cookie,
        )

        assert response.status == 403
        assert harness.backend.calls == []

    def test_a_named_person_gets_a_role_form(self, harness, signed_in):
        harness.backend.groups = [make_group(label="Ana")]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert 'action="/role"' in body
        assert "Guardar rol" in body

    def test_the_role_form_offers_the_vocabulary_as_choices_not_free_text(
        self, harness, signed_in
    ):
        harness.backend.groups = [make_group(label="Ana")]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert '<select name="role" required>' in body
        for role in ("owner", "family", "guest", "staff"):
            assert f'<option value="{role}">{role}</option>' in body
        assert 'name="role" maxlength' not in body
        assert "Elegir rol" in body

    def test_the_current_role_is_the_selected_choice_and_there_is_no_placeholder(
        self, harness, signed_in
    ):
        harness.backend.groups = [make_group(label="Ana", role="family")]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert '<option value="family" selected>family</option>' in body
        assert "Elegir rol" not in body

    def test_a_role_that_left_the_config_stays_as_the_current_choice(self, harness, signed_in):
        harness.backend.groups = [make_group(label="Ana", role="vecino")]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert '<option value="vecino" selected>vecino</option>' in body

    def test_an_empty_vocabulary_shows_no_role_form(self, harness, signed_in):
        harness.backend.vocabulary = ()
        harness.backend.groups = [make_group(label="Ana")]

        assert 'action="/role"' not in body_of(get(harness.app, "/", signed_in.cookie))

    def test_a_person_without_a_name_gets_no_role_form(self, harness, signed_in):
        harness.backend.groups = [make_group(label=None, state="unknown")]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert 'action="/role"' not in body

    def test_the_saved_message_is_shown(self, harness, signed_in):
        body = body_of(get(harness.app, "/?msg=role", signed_in.cookie))

        assert "Rol guardado." in body


class TestLiveStream:
    def test_a_camera_without_a_frame_has_no_stream(self, harness, signed_in):
        assert get(harness.app, "/camera/cuarto/stream", signed_in.cookie).status == 404

    def test_the_stream_is_never_served_without_a_session(self, harness):
        harness.backend.frames["cuarto"] = b"frame"

        response = get(harness.app, "/camera/cuarto/stream")

        assert response.status == 303
        assert response.stream is None

    def test_a_stream_is_a_motion_jpeg_that_starts_with_the_current_frame(
        self, harness, signed_in
    ):
        harness.backend.frames["cuarto"] = b"\xff\xd8frame"
        response = get(harness.app, "/camera/cuarto/stream", signed_in.cookie)

        try:
            first = next(response.stream)
        finally:
            response.stream.close()

        assert response.status == 200
        assert response.content_type == "multipart/x-mixed-replace; boundary=janusframe"
        assert first == (
            b"--janusframe\r\nContent-Type: image/jpeg\r\nContent-Length: 7\r\n\r\n"
            b"\xff\xd8frame\r\n"
        )

    def test_a_stream_carries_the_security_headers_and_no_length(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"frame"
        response = get(harness.app, "/camera/cuarto/stream", signed_in.cookie)
        response.stream.close()

        assert "default-src 'none'" in header(response, "Content-Security-Policy")
        assert header(response, "Content-Length") is None
        assert response.body == b""

    def test_each_part_carries_the_frame_the_camera_has_at_that_moment(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"one"
        stream = get(harness.app, "/camera/cuarto/stream", signed_in.cookie).stream

        try:
            first = next(stream)
            harness.backend.frames["cuarto"] = b"two"
            second = next(stream)
        finally:
            stream.close()

        assert b"one" in first
        assert b"two" in second

    def test_only_a_few_streams_can_be_open_at_once(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"frame"

        opened, refusal = open_streams_until_refused(harness.app, signed_in.cookie)

        assert opened
        assert refusal.status == 503
        for response in opened:
            response.stream.close()

    def test_closing_a_stream_frees_its_slot(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"frame"
        opened, _ = open_streams_until_refused(harness.app, signed_in.cookie)

        opened[0].stream.close()
        reopened = get(harness.app, "/camera/cuarto/stream", signed_in.cookie)

        assert reopened.status == 200
        for response in (*opened[1:], reopened):
            response.stream.close()

    def test_closing_a_stream_twice_frees_only_one_slot(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"frame"
        response = get(harness.app, "/camera/cuarto/stream", signed_in.cookie)

        response.stream.close()
        # A bounded semaphore raises when it is released more times than taken.
        response.stream.close()

    def test_closing_the_app_ends_open_streams_and_frees_their_slots(self, harness, signed_in):
        harness.backend.frames["cuarto"] = b"frame"
        opened, _ = open_streams_until_refused(harness.app, signed_in.cookie)

        harness.app.close()

        for response in opened:
            with pytest.raises(StopIteration):
                next(response.stream)
        assert get(harness.app, "/camera/cuarto/stream", signed_in.cookie).status == 200


class TestMerge:
    def test_merging_calls_the_backend_audits_and_returns_to_the_target(self, harness, signed_in):
        response = act(
            harness, signed_in, "/merge", person_id=PERSON_ID, target_id=OTHER_ID, back=OTHER_ID
        )

        assert header(response, "Location") == f"/?msg=merged#p-{OTHER_ID}"
        assert harness.backend.calls == [("merge_persons", PERSON_ID, OTHER_ID)]
        assert harness.audit == [
            ("review_merge_persons", {"source_id": PERSON_ID, "target_id": OTHER_ID})
        ]

    @pytest.mark.parametrize(
        ("person_id", "target_id"),
        [(PERSON_ID, PERSON_ID), (PERSON_ID, "x"), ("x", OTHER_ID), (PERSON_ID, "")],
    )
    def test_a_merge_needs_two_different_valid_ids(self, harness, signed_in, person_id, target_id):
        response = act(harness, signed_in, "/merge", person_id=person_id, target_id=target_id)

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []

    def test_a_refused_merge_becomes_a_flash_message(self, harness, signed_in):
        harness.backend.failure = PresenceError("no such person")

        response = act(harness, signed_in, "/merge", person_id=PERSON_ID, target_id=OTHER_ID)

        assert header(response, "Location") == "/?msg=refused"

    def test_a_person_the_evidence_points_at_is_offered_as_a_merge(self, harness, signed_in):
        item = EvidenceItem(EVIDENCE_ID, NOW, "cuarto")
        harness.backend.groups = [
            PersonGroup(
                PERSON_ID, None, "unknown", None, False, NOW, NOW, (item,), OTHER_ID, "Joanfer"
            )
        ]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert 'action="/merge"' in body
        assert f'name="target_id" value="{OTHER_ID}"' in body
        assert "Sí, es Joanfer" in body


class TestBulk:
    @pytest.mark.parametrize("decision", ["confirm", "reject", "discard"])
    def test_a_bulk_decision_reaches_the_backend_and_is_audited(self, harness, signed_in, decision):
        response = act(
            harness, signed_in, "/bulk", person_id=PERSON_ID, decision=decision, back=PERSON_ID
        )

        assert header(response, "Location") == f"/?msg=bulk_{decision}#p-{PERSON_ID}"
        assert harness.backend.calls == [("resolve_all", PERSON_ID, decision)]
        assert harness.audit == [(f"review_bulk_{decision}", {"person_id": PERSON_ID})]

    @pytest.mark.parametrize("decision", ["", "erase", "CONFIRM"])
    def test_an_unknown_decision_is_invalid(self, harness, signed_in, decision):
        response = act(harness, signed_in, "/bulk", person_id=PERSON_ID, decision=decision)

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []

    def test_a_bulk_on_a_bad_id_is_invalid(self, harness, signed_in):
        response = act(harness, signed_in, "/bulk", person_id="x", decision="confirm")

        assert header(response, "Location") == "/?msg=invalid"

    def test_a_person_with_several_rows_gets_the_bulk_bar(self, harness, signed_in):
        items = tuple(
            EvidenceItem(f"{index:08x}-bbbb-cccc-dddd-eeeeeeeeeeee", NOW, "cuarto")
            for index in range(3)
        )
        harness.backend.groups = [
            PersonGroup(PERSON_ID, "Ana", "provisional", None, False, NOW, NOW, items)
        ]

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert body.count('action="/bulk"') == 3
        assert 'data-confirm="' in body

    def test_a_lone_row_has_no_bulk_bar(self, harness, signed_in):
        harness.backend.groups = [make_group()]

        assert 'action="/bulk"' not in body_of(get(harness.app, "/", signed_in.cookie))


class TestSettings:
    def test_the_current_thresholds_are_shown(self, harness, signed_in):
        harness.backend.thresholds = (0.9, 1.4)

        body = body_of(get(harness.app, "/", signed_in.cookie))

        assert 'name="match_threshold" value="0.9"' in body
        assert 'name="match_threshold_ambiguous" value="1.4"' in body

    def test_valid_thresholds_reach_the_backend(self, harness, signed_in):
        response = act(
            harness,
            signed_in,
            "/settings",
            match_threshold="0.8",
            match_threshold_ambiguous="1.2",
        )

        assert header(response, "Location") == "/?msg=settings"
        assert harness.backend.calls == [("set_match_thresholds", 0.8, 1.2)]
        assert harness.audit == [("review_set_match_thresholds", {"match": 0.8, "ambiguous": 1.2})]

    @pytest.mark.parametrize(
        ("match", "ambiguous"),
        [
            ("1.3", "1.0"),
            ("1.0", "1.0"),
            ("0", "1.0"),
            ("-1", "1.0"),
            ("nan", "1.0"),
            ("inf", "1.0"),
            ("abc", "1.0"),
            ("1.0", "5"),
            ("", ""),
        ],
    )
    def test_thresholds_that_are_out_of_order_or_out_of_range_are_invalid(
        self, harness, signed_in, match, ambiguous
    ):
        response = act(
            harness,
            signed_in,
            "/settings",
            match_threshold=match,
            match_threshold_ambiguous=ambiguous,
        )

        assert header(response, "Location") == "/?msg=invalid"
        assert harness.backend.calls == []
