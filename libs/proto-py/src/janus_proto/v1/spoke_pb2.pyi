from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from janus_proto.v1 import capability_pb2 as _capability_pb2
from janus_proto.v1 import semantic_pb2 as _semantic_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SpokeKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SPOKE_KIND_UNSPECIFIED: _ClassVar[SpokeKind]
    SPOKE_KIND_REASONING: _ClassVar[SpokeKind]
    SPOKE_KIND_EXECUTION: _ClassVar[SpokeKind]
    SPOKE_KIND_CHANNEL: _ClassVar[SpokeKind]

class HealthState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HEALTH_STATE_UNSPECIFIED: _ClassVar[HealthState]
    HEALTH_STATE_HEALTHY: _ClassVar[HealthState]
    HEALTH_STATE_DEGRADED: _ClassVar[HealthState]
    HEALTH_STATE_UNAVAILABLE: _ClassVar[HealthState]
SPOKE_KIND_UNSPECIFIED: SpokeKind
SPOKE_KIND_REASONING: SpokeKind
SPOKE_KIND_EXECUTION: SpokeKind
SPOKE_KIND_CHANNEL: SpokeKind
HEALTH_STATE_UNSPECIFIED: HealthState
HEALTH_STATE_HEALTHY: HealthState
HEALTH_STATE_DEGRADED: HealthState
HEALTH_STATE_UNAVAILABLE: HealthState

class HealthReport(_message.Message):
    __slots__ = ("state", "checked_at", "reason", "retry_after", "requires_user_action", "details")
    class DetailsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STATE_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    RETRY_AFTER_FIELD_NUMBER: _ClassVar[int]
    REQUIRES_USER_ACTION_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    state: HealthState
    checked_at: _timestamp_pb2.Timestamp
    reason: str
    retry_after: _timestamp_pb2.Timestamp
    requires_user_action: bool
    details: _containers.ScalarMap[str, str]
    def __init__(self, state: _Optional[_Union[HealthState, str]] = ..., checked_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., reason: _Optional[str] = ..., retry_after: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., requires_user_action: bool = ..., details: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SpokeRegistration(_message.Message):
    __slots__ = ("spoke_id", "display_name", "kinds", "capabilities", "endpoint", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    KINDS_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    spoke_id: str
    display_name: str
    kinds: _containers.RepeatedScalarFieldContainer[SpokeKind]
    capabilities: _containers.RepeatedCompositeFieldContainer[_capability_pb2.CapabilityDescriptor]
    endpoint: str
    labels: _containers.ScalarMap[str, str]
    def __init__(self, spoke_id: _Optional[str] = ..., display_name: _Optional[str] = ..., kinds: _Optional[_Iterable[_Union[SpokeKind, str]]] = ..., capabilities: _Optional[_Iterable[_Union[_capability_pb2.CapabilityDescriptor, _Mapping]]] = ..., endpoint: _Optional[str] = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...
