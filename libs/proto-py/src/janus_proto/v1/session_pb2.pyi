from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SessionKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SESSION_KIND_UNSPECIFIED: _ClassVar[SessionKind]
    SESSION_KIND_JANUS_MAIN: _ClassVar[SessionKind]
    SESSION_KIND_AGENT_TASK: _ClassVar[SessionKind]

class SessionStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SESSION_STATUS_UNSPECIFIED: _ClassVar[SessionStatus]
    SESSION_STATUS_OPEN: _ClassVar[SessionStatus]
    SESSION_STATUS_CLOSED: _ClassVar[SessionStatus]

class ParticipantKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PARTICIPANT_KIND_UNSPECIFIED: _ClassVar[ParticipantKind]
    PARTICIPANT_KIND_JANUS: _ClassVar[ParticipantKind]
    PARTICIPANT_KIND_AGENT: _ClassVar[ParticipantKind]
    PARTICIPANT_KIND_USER_LISTENER: _ClassVar[ParticipantKind]
SESSION_KIND_UNSPECIFIED: SessionKind
SESSION_KIND_JANUS_MAIN: SessionKind
SESSION_KIND_AGENT_TASK: SessionKind
SESSION_STATUS_UNSPECIFIED: SessionStatus
SESSION_STATUS_OPEN: SessionStatus
SESSION_STATUS_CLOSED: SessionStatus
PARTICIPANT_KIND_UNSPECIFIED: ParticipantKind
PARTICIPANT_KIND_JANUS: ParticipantKind
PARTICIPANT_KIND_AGENT: ParticipantKind
PARTICIPANT_KIND_USER_LISTENER: ParticipantKind

class Participant(_message.Message):
    __slots__ = ("participant_id", "kind", "channel_ref", "joined_at", "left_at")
    PARTICIPANT_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_REF_FIELD_NUMBER: _ClassVar[int]
    JOINED_AT_FIELD_NUMBER: _ClassVar[int]
    LEFT_AT_FIELD_NUMBER: _ClassVar[int]
    participant_id: str
    kind: ParticipantKind
    channel_ref: str
    joined_at: _timestamp_pb2.Timestamp
    left_at: _timestamp_pb2.Timestamp
    def __init__(self, participant_id: _Optional[str] = ..., kind: _Optional[_Union[ParticipantKind, str]] = ..., channel_ref: _Optional[str] = ..., joined_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., left_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Session(_message.Message):
    __slots__ = ("session_id", "kind", "agent_name", "task_id", "status", "external_listener_count", "created_at", "closed_at")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_LISTENER_COUNT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    CLOSED_AT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    kind: SessionKind
    agent_name: str
    task_id: str
    status: SessionStatus
    external_listener_count: int
    created_at: _timestamp_pb2.Timestamp
    closed_at: _timestamp_pb2.Timestamp
    def __init__(self, session_id: _Optional[str] = ..., kind: _Optional[_Union[SessionKind, str]] = ..., agent_name: _Optional[str] = ..., task_id: _Optional[str] = ..., status: _Optional[_Union[SessionStatus, str]] = ..., external_listener_count: _Optional[int] = ..., created_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., closed_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
