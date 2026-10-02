from __future__ import annotations

import uuid

from janus_proto.v1 import common_pb2, semantic_pb2

TEXT_CONTENT_TYPE = "text/plain"


def new_request_id() -> str:
    return uuid.uuid4().hex


def is_terminal(event: semantic_pb2.SemanticEvent) -> bool:
    return event.kind == semantic_pb2.EVENT_KIND_TERMINAL


def progress_event(
    request: semantic_pb2.SemanticRequest,
    seq: int,
    delta: common_pb2.Payload | str,
) -> semantic_pb2.SemanticEvent:
    return _delta_event(request, seq, semantic_pb2.EVENT_KIND_PROGRESS, delta)


def partial_event(
    request: semantic_pb2.SemanticRequest,
    seq: int,
    delta: common_pb2.Payload | str,
) -> semantic_pb2.SemanticEvent:
    return _delta_event(request, seq, semantic_pb2.EVENT_KIND_PARTIAL, delta)


def terminal_event(
    request: semantic_pb2.SemanticRequest,
    response: semantic_pb2.SemanticResponse,
    seq: int = 0,
) -> semantic_pb2.SemanticEvent:
    event = _base_event(request, seq, semantic_pb2.EVENT_KIND_TERMINAL)
    event.response.CopyFrom(response)
    return event


def _delta_event(
    request: semantic_pb2.SemanticRequest,
    seq: int,
    kind: semantic_pb2.EventKind,
    delta: common_pb2.Payload | str,
) -> semantic_pb2.SemanticEvent:
    event = _base_event(request, seq, kind)
    event.delta.CopyFrom(_as_payload(delta))
    return event


def _base_event(
    request: semantic_pb2.SemanticRequest,
    seq: int,
    kind: semantic_pb2.EventKind,
) -> semantic_pb2.SemanticEvent:
    event = semantic_pb2.SemanticEvent(
        request_id=request.request_id,
        seq=seq,
        kind=kind,
        session_id=request.session_id,
    )
    if request.HasField("task_id"):
        event.task_id = request.task_id
    if request.HasField("role"):
        event.role = request.role
    event.at.GetCurrentTime()
    return event


def _as_payload(delta: common_pb2.Payload | str) -> common_pb2.Payload:
    if isinstance(delta, str):
        return common_pb2.Payload(text=delta, content_type=TEXT_CONTENT_TYPE)
    return delta
