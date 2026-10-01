from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Payload(_message.Message):
    __slots__ = ("text", "json", "binary", "content_type")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    JSON_FIELD_NUMBER: _ClassVar[int]
    BINARY_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    text: str
    json: _struct_pb2.Struct
    binary: bytes
    content_type: str
    def __init__(self, text: _Optional[str] = ..., json: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., binary: _Optional[bytes] = ..., content_type: _Optional[str] = ...) -> None: ...

class Artifact(_message.Message):
    __slots__ = ("artifact_id", "kind", "uri", "content_type", "size_bytes", "sha256", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ARTIFACT_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    URI_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    artifact_id: str
    kind: str
    uri: str
    content_type: str
    size_bytes: int
    sha256: str
    labels: _containers.ScalarMap[str, str]
    def __init__(self, artifact_id: _Optional[str] = ..., kind: _Optional[str] = ..., uri: _Optional[str] = ..., content_type: _Optional[str] = ..., size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ErrorInfo(_message.Message):
    __slots__ = ("code", "message", "retryable", "side_effects_possible", "details")
    class DetailsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RETRYABLE_FIELD_NUMBER: _ClassVar[int]
    SIDE_EFFECTS_POSSIBLE_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    code: str
    message: str
    retryable: bool
    side_effects_possible: bool
    details: _containers.ScalarMap[str, str]
    def __init__(self, code: _Optional[str] = ..., message: _Optional[str] = ..., retryable: bool = ..., side_effects_possible: bool = ..., details: _Optional[_Mapping[str, str]] = ...) -> None: ...
