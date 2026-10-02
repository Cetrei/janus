import pytest
from google.protobuf import duration_pb2, struct_pb2, timestamp_pb2

from janus_proto import (
    Artifact,
    CachePolicy,
    CachePolicyKind,
    CapabilityDescriptor,
    DeliveryReceipt,
    ErrorInfo,
    EventKind,
    HealthReport,
    HealthState,
    IdentityMode,
    InboundEvent,
    OutboundMessage,
    Participant,
    ParticipantKind,
    Payload,
    ResponseStatus,
    SemanticEvent,
    SemanticRequest,
    SemanticResponse,
    Session,
    SessionKind,
    SessionStatus,
    SpeakerIdentity,
    SpokeKind,
    SpokeRegistration,
    Task,
    TaskChecklistItem,
    TaskSpec,
    TaskStatus,
    UntrustedSender,
)

MAX_UINT64 = 2**64 - 1
MAX_UINT32 = 2**32 - 1


def struct_of(**values) -> struct_pb2.Struct:
    result = struct_pb2.Struct()
    result.update(values)
    return result


def timestamp_at(seconds: int) -> timestamp_pb2.Timestamp:
    return timestamp_pb2.Timestamp(seconds=seconds, nanos=999_999_999)


def roundtrip(message):
    parsed = type(message)()
    parsed.ParseFromString(message.SerializeToString())
    return parsed


def full_request() -> SemanticRequest:
    return SemanticRequest(
        request_id="r",
        capability_id="reasoning.complete",
        session_id="s",
        task_id="t",
        role="planner",
        input=Payload(text="hola", content_type="text/plain"),
        metadata={"k": "v", "": ""},
        deadline=duration_pb2.Duration(seconds=30, nanos=500),
        route_trace=["a", "b"],
        requester_id="user",
        attachments=[Payload(binary=b"\x00" * 16), Payload(json=struct_of(a=1))],
    )


def full_response() -> SemanticResponse:
    return SemanticResponse(
        status=ResponseStatus.FAILED,
        output=Payload(json=struct_of(ok=False)),
        artifacts=[Artifact(artifact_id="a", size_bytes=MAX_UINT64, labels={"x": "y"})],
        suggested_next_step="retry",
        error=ErrorInfo(
            code="E1",
            message="boom",
            retryable=True,
            side_effects_possible=True,
            details={"d": "1"},
        ),
    )


MESSAGES = {
    "payload_text": Payload(text="x", content_type="text/plain"),
    "payload_json": Payload(json=struct_of(n=1.5, s="t", nested={"a": [1, 2]})),
    "payload_binary": Payload(binary=bytes(range(256))),
    "payload_empty": Payload(),
    "artifact": Artifact(
        artifact_id="a", kind="image", uri="file:///x", size_bytes=MAX_UINT64, sha256="0" * 64
    ),
    "error_info": ErrorInfo(code="c", message="m", retryable=True, side_effects_possible=True),
    "request": full_request(),
    "request_minimal": SemanticRequest(),
    "response": full_response(),
    "response_minimal": SemanticResponse(),
    "event_partial": SemanticEvent(
        request_id="r",
        seq=MAX_UINT64,
        kind=EventKind.PARTIAL,
        delta=Payload(text="d"),
        at=timestamp_at(1_700_000_000),
    ),
    "event_terminal": SemanticEvent(
        request_id="r", kind=EventKind.TERMINAL, response=full_response()
    ),
    "cache_policy": CachePolicy(kind=CachePolicyKind.TTL, ttl=duration_pb2.Duration(seconds=60)),
    "capability_descriptor": CapabilityDescriptor(
        capability_id="home.lights.set",
        version="1.0.0",
        description="d",
        input_content_types=["application/json"],
        output_content_types=["text/plain"],
        input_schema=struct_of(type="object"),
        output_schema=struct_of(type="string"),
        cache_policy=CachePolicy(kind=CachePolicyKind.NONE),
        idempotent=True,
        labels={"a": "b"},
    ),
    "checklist_item": TaskChecklistItem(
        item_id="i", label="l", done=True, done_at=timestamp_at(5)
    ),
    "task_spec": TaskSpec(
        title="t",
        role="r",
        session_id="s",
        depends_on=["x", "y"],
        input=Payload(text="i"),
        labels={"a": "b"},
        checklist=[TaskChecklistItem(item_id="1", label="one")],
        required=True,
    ),
    "task": Task(
        task_id="t",
        spec=TaskSpec(title="x", required=True),
        status=TaskStatus.COMPLETED,
        assigned_spoke_id="spoke",
        created_at=timestamp_at(1),
        started_at=timestamp_at(2),
        finished_at=timestamp_at(3),
        result=full_response(),
        status_reason="ok",
        attempts=MAX_UINT32,
    ),
    "participant": Participant(
        participant_id="p",
        kind=ParticipantKind.USER_LISTENER,
        channel_ref="c",
        joined_at=timestamp_at(1),
        left_at=timestamp_at(2),
    ),
    "session": Session(
        session_id="s",
        kind=SessionKind.AGENT_TASK,
        agent_name="a",
        task_id="t",
        status=SessionStatus.CLOSED,
        external_listener_count=MAX_UINT32,
        created_at=timestamp_at(1),
        closed_at=timestamp_at(2),
    ),
    "untrusted_sender": UntrustedSender(
        platform_user_id="u", display_name="d", attributes={"a": "b"}
    ),
    "inbound_event": InboundEvent(
        event_id="e",
        platform="discord",
        channel_id="c",
        account_id="a",
        sender=UntrustedSender(platform_user_id="u"),
        content=Payload(text="hi"),
        received_at=timestamp_at(1),
        metadata={"a": "b"},
    ),
    "speaker_identity": SpeakerIdentity(
        mode=IdentityMode.SHARED_WITH_PREFIX,
        agent_name="a",
        display_prefix="[a]",
        bot_account_id="b",
    ),
    "outbound_message": OutboundMessage(
        message_id="m",
        platform="discord",
        channel_id="c",
        account_id="a",
        content=Payload(text="hi"),
        speaker=SpeakerIdentity(mode=IdentityMode.JANUS),
        reply_to_event_id="e",
    ),
    "delivery_receipt": DeliveryReceipt(
        message_id="m", delivered=False, error=ErrorInfo(code="c", retryable=True)
    ),
    "health_report": HealthReport(
        state=HealthState.DEGRADED,
        checked_at=timestamp_at(1),
        reason="slow",
        retry_after=timestamp_at(9),
        requires_user_action=True,
        details={"a": "b"},
    ),
    "spoke_registration": SpokeRegistration(
        spoke_id="s",
        display_name="d",
        kinds=[SpokeKind.REASONING, SpokeKind.EXECUTION],
        capabilities=[CapabilityDescriptor(capability_id="reasoning.complete")],
        endpoint="127.0.0.1:50051",
        labels={"a": "b"},
    ),
}


@pytest.mark.parametrize("name", sorted(MESSAGES))
def test_should_roundtrip_message_without_loss(name):
    message = MESSAGES[name]

    assert roundtrip(message) == message


@pytest.mark.parametrize("name", sorted(MESSAGES))
def test_should_serialize_deterministically(name):
    message = MESSAGES[name]

    first = message.SerializeToString(deterministic=True)
    second = type(message).FromString(first).SerializeToString(deterministic=True)

    assert first == second


def test_should_keep_oneof_choice_after_roundtrip():
    parsed = roundtrip(MESSAGES["payload_binary"])

    assert parsed.WhichOneof("kind") == "binary"
    assert parsed.binary == bytes(range(256))


def test_should_treat_payload_without_oneof_as_empty():
    parsed = roundtrip(Payload())

    assert parsed.WhichOneof("kind") is None


def test_should_distinguish_unset_optional_from_empty_string():
    unset = SemanticRequest()
    empty = SemanticRequest(task_id="")

    assert not roundtrip(unset).HasField("task_id")
    assert roundtrip(empty).HasField("task_id")


def test_should_keep_optional_message_presence_on_terminal_event():
    with_response = roundtrip(MESSAGES["event_terminal"])
    without_response = roundtrip(SemanticEvent(kind=EventKind.PROGRESS))

    assert with_response.HasField("response")
    assert not without_response.HasField("response")


def test_should_reject_seq_beyond_uint64():
    with pytest.raises(ValueError):
        SemanticEvent(seq=MAX_UINT64 + 1)


def test_should_reject_attempts_beyond_uint32():
    with pytest.raises(ValueError):
        Task(attempts=MAX_UINT32 + 1)


def test_should_default_cache_policy_to_unset_and_idempotent_to_false():
    descriptor = CapabilityDescriptor(capability_id="a.b")

    assert not descriptor.HasField("cache_policy")
    assert descriptor.idempotent is False


def test_should_keep_done_at_independent_from_done():
    item = TaskChecklistItem(item_id="i", done_at=timestamp_at(1))

    parsed = roundtrip(item)

    assert parsed.done is False
    assert parsed.HasField("done_at")
