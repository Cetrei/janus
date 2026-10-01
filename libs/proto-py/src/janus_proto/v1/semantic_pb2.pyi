from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from janus_proto.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EventKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EVENT_KIND_UNSPECIFIED: _ClassVar[EventKind]
    EVENT_KIND_PROGRESS: _ClassVar[EventKind]
    EVENT_KIND_PARTIAL: _ClassVar[EventKind]
    EVENT_KIND_TERMINAL: _ClassVar[EventKind]

class ResponseStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RESPONSE_STATUS_UNSPECIFIED: _ClassVar[ResponseStatus]
    RESPONSE_STATUS_SUCCEEDED: _ClassVar[ResponseStatus]
    RESPONSE_STATUS_FAILED: _ClassVar[ResponseStatus]
EVENT_KIND_UNSPECIFIED: EventKind
EVENT_KIND_PROGRESS: EventKind
EVENT_KIND_PARTIAL: EventKind
EVENT_KIND_TERMINAL: EventKind
RESPONSE_STATUS_UNSPECIFIED: ResponseStatus
RESPONSE_STATUS_SUCCEEDED: ResponseStatus
RESPONSE_STATUS_FAILED: ResponseStatus

class SemanticRequest(_message.Message):
    __slots__ = ("request_id", "capability_id", "session_id", "task_id", "role", "input", "metadata", "deadline", "route_trace", "requester_id", "attachments")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    INPUT_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    ROUTE_TRACE_FIELD_NUMBER: _ClassVar[int]
    REQUESTER_ID_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    capability_id: str
    session_id: str
    task_id: str
    role: str
    input: _common_pb2.Payload
    metadata: _containers.ScalarMap[str, str]
    deadline: _duration_pb2.Duration
    route_trace: _containers.RepeatedScalarFieldContainer[str]
    requester_id: str
    attachments: _containers.RepeatedCompositeFieldContainer[_common_pb2.Payload]
    def __init__(self, request_id: _Optional[str] = ..., capability_id: _Optional[str] = ..., session_id: _Optional[str] = ..., task_id: _Optional[str] = ..., role: _Optional[str] = ..., input: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., metadata: _Optional[_Mapping[str, str]] = ..., deadline: _Optional[_Union[_duration_pb2.Duration, _Mapping]] = ..., route_trace: _Optional[_Iterable[str]] = ..., requester_id: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[_common_pb2.Payload, _Mapping]]] = ...) -> None: ...

class SemanticResponse(_message.Message):
    __slots__ = ("status", "output", "artifacts", "suggested_next_step", "error")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    SUGGESTED_NEXT_STEP_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    status: ResponseStatus
    output: _common_pb2.Payload
    artifacts: _containers.RepeatedCompositeFieldContainer[_common_pb2.Artifact]
    suggested_next_step: str
    error: _common_pb2.ErrorInfo
    def __init__(self, status: _Optional[_Union[ResponseStatus, str]] = ..., output: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., artifacts: _Optional[_Iterable[_Union[_common_pb2.Artifact, _Mapping]]] = ..., suggested_next_step: _Optional[str] = ..., error: _Optional[_Union[_common_pb2.ErrorInfo, _Mapping]] = ...) -> None: ...

class SemanticEvent(_message.Message):
    __slots__ = ("request_id", "seq", "kind", "session_id", "task_id", "role", "delta", "response", "at")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    DELTA_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    AT_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    seq: int
    kind: EventKind
    session_id: str
    task_id: str
    role: str
    delta: _common_pb2.Payload
    response: SemanticResponse
    at: _timestamp_pb2.Timestamp
    def __init__(self, request_id: _Optional[str] = ..., seq: _Optional[int] = ..., kind: _Optional[_Union[EventKind, str]] = ..., session_id: _Optional[str] = ..., task_id: _Optional[str] = ..., role: _Optional[str] = ..., delta: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., response: _Optional[_Union[SemanticResponse, _Mapping]] = ..., at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
