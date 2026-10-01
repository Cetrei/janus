from google.protobuf import timestamp_pb2 as _timestamp_pb2
from janus_proto.v1 import common_pb2 as _common_pb2
from janus_proto.v1 import semantic_pb2 as _semantic_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TaskStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TASK_STATUS_UNSPECIFIED: _ClassVar[TaskStatus]
    TASK_STATUS_PENDING: _ClassVar[TaskStatus]
    TASK_STATUS_RUNNING: _ClassVar[TaskStatus]
    TASK_STATUS_BLOCKED: _ClassVar[TaskStatus]
    TASK_STATUS_COMPLETED: _ClassVar[TaskStatus]
    TASK_STATUS_FAILED: _ClassVar[TaskStatus]
    TASK_STATUS_CANCELLED: _ClassVar[TaskStatus]
TASK_STATUS_UNSPECIFIED: TaskStatus
TASK_STATUS_PENDING: TaskStatus
TASK_STATUS_RUNNING: TaskStatus
TASK_STATUS_BLOCKED: TaskStatus
TASK_STATUS_COMPLETED: TaskStatus
TASK_STATUS_FAILED: TaskStatus
TASK_STATUS_CANCELLED: TaskStatus

class TaskChecklistItem(_message.Message):
    __slots__ = ("item_id", "label", "done", "done_at")
    ITEM_ID_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    DONE_AT_FIELD_NUMBER: _ClassVar[int]
    item_id: str
    label: str
    done: bool
    done_at: _timestamp_pb2.Timestamp
    def __init__(self, item_id: _Optional[str] = ..., label: _Optional[str] = ..., done: bool = ..., done_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TaskSpec(_message.Message):
    __slots__ = ("title", "role", "session_id", "depends_on", "input", "labels", "checklist", "required")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    TITLE_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    DEPENDS_ON_FIELD_NUMBER: _ClassVar[int]
    INPUT_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    CHECKLIST_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_FIELD_NUMBER: _ClassVar[int]
    title: str
    role: str
    session_id: str
    depends_on: _containers.RepeatedScalarFieldContainer[str]
    input: _common_pb2.Payload
    labels: _containers.ScalarMap[str, str]
    checklist: _containers.RepeatedCompositeFieldContainer[TaskChecklistItem]
    required: bool
    def __init__(self, title: _Optional[str] = ..., role: _Optional[str] = ..., session_id: _Optional[str] = ..., depends_on: _Optional[_Iterable[str]] = ..., input: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., labels: _Optional[_Mapping[str, str]] = ..., checklist: _Optional[_Iterable[_Union[TaskChecklistItem, _Mapping]]] = ..., required: bool = ...) -> None: ...

class Task(_message.Message):
    __slots__ = ("task_id", "spec", "status", "assigned_spoke_id", "created_at", "started_at", "finished_at", "result", "status_reason", "attempts")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    SPEC_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_SPOKE_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    FINISHED_AT_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    STATUS_REASON_FIELD_NUMBER: _ClassVar[int]
    ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    spec: TaskSpec
    status: TaskStatus
    assigned_spoke_id: str
    created_at: _timestamp_pb2.Timestamp
    started_at: _timestamp_pb2.Timestamp
    finished_at: _timestamp_pb2.Timestamp
    result: _semantic_pb2.SemanticResponse
    status_reason: str
    attempts: int
    def __init__(self, task_id: _Optional[str] = ..., spec: _Optional[_Union[TaskSpec, _Mapping]] = ..., status: _Optional[_Union[TaskStatus, str]] = ..., assigned_spoke_id: _Optional[str] = ..., created_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., started_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., finished_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., result: _Optional[_Union[_semantic_pb2.SemanticResponse, _Mapping]] = ..., status_reason: _Optional[str] = ..., attempts: _Optional[int] = ...) -> None: ...
