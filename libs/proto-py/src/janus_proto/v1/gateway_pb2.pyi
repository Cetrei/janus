from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from janus_proto.v1 import capability_pb2 as _capability_pb2
from janus_proto.v1 import channel_pb2 as _channel_pb2
from janus_proto.v1 import semantic_pb2 as _semantic_pb2
from janus_proto.v1 import session_pb2 as _session_pb2
from janus_proto.v1 import spoke_pb2 as _spoke_pb2
from janus_proto.v1 import task_pb2 as _task_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AvailabilityMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AVAILABILITY_MODE_UNSPECIFIED: _ClassVar[AvailabilityMode]
    AVAILABILITY_MODE_AUTO: _ClassVar[AvailabilityMode]
    AVAILABILITY_MODE_UNAVAILABLE_UNTIL: _ClassVar[AvailabilityMode]
    AVAILABILITY_MODE_UNAVAILABLE_INDEFINITE: _ClassVar[AvailabilityMode]

class CapabilityChangeKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CAPABILITY_CHANGE_KIND_UNSPECIFIED: _ClassVar[CapabilityChangeKind]
    CAPABILITY_CHANGE_KIND_ADDED: _ClassVar[CapabilityChangeKind]
    CAPABILITY_CHANGE_KIND_UPDATED: _ClassVar[CapabilityChangeKind]
    CAPABILITY_CHANGE_KIND_REMOVED: _ClassVar[CapabilityChangeKind]
AVAILABILITY_MODE_UNSPECIFIED: AvailabilityMode
AVAILABILITY_MODE_AUTO: AvailabilityMode
AVAILABILITY_MODE_UNAVAILABLE_UNTIL: AvailabilityMode
AVAILABILITY_MODE_UNAVAILABLE_INDEFINITE: AvailabilityMode
CAPABILITY_CHANGE_KIND_UNSPECIFIED: CapabilityChangeKind
CAPABILITY_CHANGE_KIND_ADDED: CapabilityChangeKind
CAPABILITY_CHANGE_KIND_UPDATED: CapabilityChangeKind
CAPABILITY_CHANGE_KIND_REMOVED: CapabilityChangeKind

class RegisterAck(_message.Message):
    __slots__ = ("spoke_id", "heartbeat_interval")
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_INTERVAL_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    heartbeat_interval: _duration_pb2.Duration
    def __init__(self, spoke_id: _Optional[str] = ..., heartbeat_interval: _Optional[_Union[_duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("spoke_id", "report")
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    REPORT_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    report: _spoke_pb2.HealthReport
    def __init__(self, spoke_id: _Optional[str] = ..., report: _Optional[_Union[_spoke_pb2.HealthReport, _Mapping]] = ...) -> None: ...

class HealthAck(_message.Message):
    __slots__ = ("received_at",)
    RECEIVED_AT_FIELD_NUMBER: _ClassVar[int]
    received_at: _timestamp_pb2.Timestamp
    def __init__(self, received_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class UnregisterRequest(_message.Message):
    __slots__ = ("spoke_id",)
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    def __init__(self, spoke_id: _Optional[str] = ...) -> None: ...

class ChannelHello(_message.Message):
    __slots__ = ("gateway_id", "platforms")
    GATEWAY_ID_FIELD_NUMBER: _ClassVar[int]
    PLATFORMS_FIELD_NUMBER: _ClassVar[int]
    gateway_id: str
    platforms: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, gateway_id: _Optional[str] = ..., platforms: _Optional[_Iterable[str]] = ...) -> None: ...

class ChannelAck(_message.Message):
    __slots__ = ("event_id",)
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    event_id: str
    def __init__(self, event_id: _Optional[str] = ...) -> None: ...

class ChannelUp(_message.Message):
    __slots__ = ("hello", "inbound", "receipt")
    HELLO_FIELD_NUMBER: _ClassVar[int]
    INBOUND_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    hello: ChannelHello
    inbound: _channel_pb2.InboundEvent
    receipt: _channel_pb2.DeliveryReceipt
    def __init__(self, hello: _Optional[_Union[ChannelHello, _Mapping]] = ..., inbound: _Optional[_Union[_channel_pb2.InboundEvent, _Mapping]] = ..., receipt: _Optional[_Union[_channel_pb2.DeliveryReceipt, _Mapping]] = ...) -> None: ...

class ChannelDown(_message.Message):
    __slots__ = ("outbound", "ack")
    OUTBOUND_FIELD_NUMBER: _ClassVar[int]
    ACK_FIELD_NUMBER: _ClassVar[int]
    outbound: _channel_pb2.OutboundMessage
    ack: ChannelAck
    def __init__(self, outbound: _Optional[_Union[_channel_pb2.OutboundMessage, _Mapping]] = ..., ack: _Optional[_Union[ChannelAck, _Mapping]] = ...) -> None: ...

class TaskRef(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class AssignRoleRequest(_message.Message):
    __slots__ = ("role", "spoke_id")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    role: str
    spoke_id: str
    def __init__(self, role: _Optional[str] = ..., spoke_id: _Optional[str] = ...) -> None: ...

class CreateSessionRequest(_message.Message):
    __slots__ = ("kind", "agent_name", "task_id")
    KIND_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    kind: _session_pb2.SessionKind
    agent_name: str
    task_id: str
    def __init__(self, kind: _Optional[_Union[_session_pb2.SessionKind, str]] = ..., agent_name: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class SubscribeRequest(_message.Message):
    __slots__ = ("session_id", "participant_id", "channel_ref")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PARTICIPANT_ID_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_REF_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    participant_id: str
    channel_ref: str
    def __init__(self, session_id: _Optional[str] = ..., participant_id: _Optional[str] = ..., channel_ref: _Optional[str] = ...) -> None: ...

class SetPreferenceRequest(_message.Message):
    __slots__ = ("key", "value")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: _struct_pb2.Value
    def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ...) -> None: ...

class SetSpokeAvailabilityRequest(_message.Message):
    __slots__ = ("spoke_id", "mode", "until", "reason")
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    UNTIL_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    mode: AvailabilityMode
    until: _timestamp_pb2.Timestamp
    reason: str
    def __init__(self, spoke_id: _Optional[str] = ..., mode: _Optional[_Union[AvailabilityMode, str]] = ..., until: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., reason: _Optional[str] = ...) -> None: ...

class ListRequest(_message.Message):
    __slots__ = ("page_size", "page_token")
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    page_size: int
    page_token: str
    def __init__(self, page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class RegistrySnapshot(_message.Message):
    __slots__ = ("spokes", "role_assignments")
    class RoleAssignmentsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SPOKES_FIELD_NUMBER: _ClassVar[int]
    ROLE_ASSIGNMENTS_FIELD_NUMBER: _ClassVar[int]
    spokes: _containers.RepeatedCompositeFieldContainer[_spoke_pb2.SpokeRegistration]
    role_assignments: _containers.ScalarMap[str, str]
    def __init__(self, spokes: _Optional[_Iterable[_Union[_spoke_pb2.SpokeRegistration, _Mapping]]] = ..., role_assignments: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SessionList(_message.Message):
    __slots__ = ("sessions", "next_page_token")
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    sessions: _containers.RepeatedCompositeFieldContainer[_session_pb2.Session]
    next_page_token: str
    def __init__(self, sessions: _Optional[_Iterable[_Union[_session_pb2.Session, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class TaskList(_message.Message):
    __slots__ = ("tasks", "next_page_token")
    TASKS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    tasks: _containers.RepeatedCompositeFieldContainer[_task_pb2.Task]
    next_page_token: str
    def __init__(self, tasks: _Optional[_Iterable[_Union[_task_pb2.Task, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class AgentInfo(_message.Message):
    __slots__ = ("agent_name", "role", "spoke_id")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    role: str
    spoke_id: str
    def __init__(self, agent_name: _Optional[str] = ..., role: _Optional[str] = ..., spoke_id: _Optional[str] = ...) -> None: ...

class AgentList(_message.Message):
    __slots__ = ("agents",)
    AGENTS_FIELD_NUMBER: _ClassVar[int]
    agents: _containers.RepeatedCompositeFieldContainer[AgentInfo]
    def __init__(self, agents: _Optional[_Iterable[_Union[AgentInfo, _Mapping]]] = ...) -> None: ...

class PreferenceSet(_message.Message):
    __slots__ = ("preferences",)
    class PreferencesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: _struct_pb2.Value
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ...) -> None: ...
    PREFERENCES_FIELD_NUMBER: _ClassVar[int]
    preferences: _containers.MessageMap[str, _struct_pb2.Value]
    def __init__(self, preferences: _Optional[_Mapping[str, _struct_pb2.Value]] = ...) -> None: ...

class WatchRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CapabilityChange(_message.Message):
    __slots__ = ("spoke_id", "kind", "capability")
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    kind: CapabilityChangeKind
    capability: _capability_pb2.CapabilityDescriptor
    def __init__(self, spoke_id: _Optional[str] = ..., kind: _Optional[_Union[CapabilityChangeKind, str]] = ..., capability: _Optional[_Union[_capability_pb2.CapabilityDescriptor, _Mapping]] = ...) -> None: ...

class SpokeHealthChange(_message.Message):
    __slots__ = ("spoke_id", "report")
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    REPORT_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    report: _spoke_pb2.HealthReport
    def __init__(self, spoke_id: _Optional[str] = ..., report: _Optional[_Union[_spoke_pb2.HealthReport, _Mapping]] = ...) -> None: ...

class StateEvent(_message.Message):
    __slots__ = ("task", "session", "spoke", "health", "capability")
    TASK_FIELD_NUMBER: _ClassVar[int]
    SESSION_FIELD_NUMBER: _ClassVar[int]
    SPOKE_FIELD_NUMBER: _ClassVar[int]
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    task: _task_pb2.Task
    session: _session_pb2.Session
    spoke: _spoke_pb2.SpokeRegistration
    health: SpokeHealthChange
    capability: CapabilityChange
    def __init__(self, task: _Optional[_Union[_task_pb2.Task, _Mapping]] = ..., session: _Optional[_Union[_session_pb2.Session, _Mapping]] = ..., spoke: _Optional[_Union[_spoke_pb2.SpokeRegistration, _Mapping]] = ..., health: _Optional[_Union[SpokeHealthChange, _Mapping]] = ..., capability: _Optional[_Union[CapabilityChange, _Mapping]] = ...) -> None: ...
