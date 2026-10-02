import re

from janus_proto import (
    EventKind,
    Payload,
    ResponseStatus,
    SemanticEvent,
    SemanticRequest,
    SemanticResponse,
    helpers,
)


def build_request(with_optionals: bool = True) -> SemanticRequest:
    request = SemanticRequest(
        request_id="req-1",
        capability_id="reasoning.complete",
        session_id="sess-1",
    )
    if with_optionals:
        request.task_id = "task-1"
        request.role = "planner"
    return request


def build_response() -> SemanticResponse:
    return SemanticResponse(
        status=ResponseStatus.SUCCEEDED,
        output=Payload(text="done", content_type="text/plain"),
    )


def test_should_copy_traceability_from_request_into_terminal_event():
    event = helpers.terminal_event(build_request(), build_response(), seq=7)

    assert event.request_id == "req-1"
    assert event.session_id == "sess-1"
    assert event.task_id == "task-1"
    assert event.role == "planner"
    assert event.seq == 7
    assert event.kind == EventKind.TERMINAL


def test_should_embed_the_response_in_terminal_event():
    event = helpers.terminal_event(build_request(), build_response())

    assert event.HasField("response")
    assert event.response.output.text == "done"
    assert event.response.status == ResponseStatus.SUCCEEDED


def test_should_leave_optional_fields_unset_when_request_lacks_them():
    event = helpers.terminal_event(build_request(with_optionals=False), build_response())

    assert not event.HasField("task_id")
    assert not event.HasField("role")


def test_should_preserve_explicit_empty_optional_fields():
    request = build_request(with_optionals=False)
    request.task_id = ""

    event = helpers.progress_event(request, 1, "x")

    assert event.HasField("task_id")
    assert event.task_id == ""


def test_should_stamp_the_event_with_a_timestamp():
    event = helpers.terminal_event(build_request(), build_response())

    assert event.HasField("at")
    assert event.at.seconds > 0


def test_should_build_progress_event_from_text():
    event = helpers.progress_event(build_request(), 1, "thinking")

    assert event.kind == EventKind.PROGRESS
    assert event.delta.text == "thinking"
    assert event.delta.content_type == "text/plain"
    assert not event.HasField("response")


def test_should_build_partial_event_from_payload():
    payload = Payload(binary=b"\x00\xff", content_type="application/octet-stream")

    event = helpers.partial_event(build_request(), 2, payload)

    assert event.kind == EventKind.PARTIAL
    assert event.delta.binary == b"\x00\xff"
    assert event.delta.content_type == "application/octet-stream"
    assert event.seq == 2


def test_should_flag_only_terminal_events_as_terminal():
    request = build_request()

    assert helpers.is_terminal(helpers.terminal_event(request, build_response()))
    assert not helpers.is_terminal(helpers.progress_event(request, 1, "x"))
    assert not helpers.is_terminal(helpers.partial_event(request, 2, "x"))
    assert not helpers.is_terminal(SemanticEvent())


def test_should_generate_uuid4_hex_request_ids():
    first = helpers.new_request_id()
    second = helpers.new_request_id()

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second
