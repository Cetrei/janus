import re
from enum import IntEnum
from typing import Any

from janus_proto.v1 import (
    capability_pb2,
    channel_pb2,
    gateway_pb2,
    semantic_pb2,
    session_pb2,
    spoke_pb2,
    task_pb2,
)

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _alias(wrapper: Any, name: str) -> type[IntEnum]:
    prefix = _CAMEL_BOUNDARY.sub("_", name).upper() + "_"
    members = {key.removeprefix(prefix): value for key, value in wrapper.items()}
    return IntEnum(name, members, module=__name__)


EventKind = _alias(semantic_pb2.EventKind, "EventKind")
ResponseStatus = _alias(semantic_pb2.ResponseStatus, "ResponseStatus")
CachePolicyKind = _alias(capability_pb2.CachePolicyKind, "CachePolicyKind")
TaskStatus = _alias(task_pb2.TaskStatus, "TaskStatus")
SessionKind = _alias(session_pb2.SessionKind, "SessionKind")
SessionStatus = _alias(session_pb2.SessionStatus, "SessionStatus")
ParticipantKind = _alias(session_pb2.ParticipantKind, "ParticipantKind")
IdentityMode = _alias(channel_pb2.IdentityMode, "IdentityMode")
SpokeKind = _alias(spoke_pb2.SpokeKind, "SpokeKind")
HealthState = _alias(spoke_pb2.HealthState, "HealthState")
AvailabilityMode = _alias(gateway_pb2.AvailabilityMode, "AvailabilityMode")
CapabilityChangeKind = _alias(gateway_pb2.CapabilityChangeKind, "CapabilityChangeKind")

ENUM_ALIASES = {
    "EventKind": (EventKind, semantic_pb2.EventKind),
    "ResponseStatus": (ResponseStatus, semantic_pb2.ResponseStatus),
    "CachePolicyKind": (CachePolicyKind, capability_pb2.CachePolicyKind),
    "TaskStatus": (TaskStatus, task_pb2.TaskStatus),
    "SessionKind": (SessionKind, session_pb2.SessionKind),
    "SessionStatus": (SessionStatus, session_pb2.SessionStatus),
    "ParticipantKind": (ParticipantKind, session_pb2.ParticipantKind),
    "IdentityMode": (IdentityMode, channel_pb2.IdentityMode),
    "SpokeKind": (SpokeKind, spoke_pb2.SpokeKind),
    "HealthState": (HealthState, spoke_pb2.HealthState),
    "AvailabilityMode": (AvailabilityMode, gateway_pb2.AvailabilityMode),
    "CapabilityChangeKind": (CapabilityChangeKind, gateway_pb2.CapabilityChangeKind),
}
