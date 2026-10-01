from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CachePolicyKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CACHE_POLICY_KIND_UNSPECIFIED: _ClassVar[CachePolicyKind]
    CACHE_POLICY_KIND_NONE: _ClassVar[CachePolicyKind]
    CACHE_POLICY_KIND_TTL: _ClassVar[CachePolicyKind]
CACHE_POLICY_KIND_UNSPECIFIED: CachePolicyKind
CACHE_POLICY_KIND_NONE: CachePolicyKind
CACHE_POLICY_KIND_TTL: CachePolicyKind

class CachePolicy(_message.Message):
    __slots__ = ("kind", "ttl")
    KIND_FIELD_NUMBER: _ClassVar[int]
    TTL_FIELD_NUMBER: _ClassVar[int]
    kind: CachePolicyKind
    ttl: _duration_pb2.Duration
    def __init__(self, kind: _Optional[_Union[CachePolicyKind, str]] = ..., ttl: _Optional[_Union[_duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class CapabilityDescriptor(_message.Message):
    __slots__ = ("capability_id", "version", "description", "input_content_types", "output_content_types", "input_schema", "output_schema", "cache_policy", "idempotent", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CAPABILITY_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    INPUT_CONTENT_TYPES_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_CONTENT_TYPES_FIELD_NUMBER: _ClassVar[int]
    INPUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    CACHE_POLICY_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENT_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    capability_id: str
    version: str
    description: str
    input_content_types: _containers.RepeatedScalarFieldContainer[str]
    output_content_types: _containers.RepeatedScalarFieldContainer[str]
    input_schema: _struct_pb2.Struct
    output_schema: _struct_pb2.Struct
    cache_policy: CachePolicy
    idempotent: bool
    labels: _containers.ScalarMap[str, str]
    def __init__(self, capability_id: _Optional[str] = ..., version: _Optional[str] = ..., description: _Optional[str] = ..., input_content_types: _Optional[_Iterable[str]] = ..., output_content_types: _Optional[_Iterable[str]] = ..., input_schema: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., output_schema: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., cache_policy: _Optional[_Union[CachePolicy, _Mapping]] = ..., idempotent: bool = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...
