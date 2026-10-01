from google.protobuf import timestamp_pb2 as _timestamp_pb2
from janus_proto.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class IdentityMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    IDENTITY_MODE_UNSPECIFIED: _ClassVar[IdentityMode]
    IDENTITY_MODE_JANUS: _ClassVar[IdentityMode]
    IDENTITY_MODE_OWN_BOT: _ClassVar[IdentityMode]
    IDENTITY_MODE_SHARED_WITH_PREFIX: _ClassVar[IdentityMode]
IDENTITY_MODE_UNSPECIFIED: IdentityMode
IDENTITY_MODE_JANUS: IdentityMode
IDENTITY_MODE_OWN_BOT: IdentityMode
IDENTITY_MODE_SHARED_WITH_PREFIX: IdentityMode

class UntrustedSender(_message.Message):
    __slots__ = ("platform_user_id", "display_name", "attributes")
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PLATFORM_USER_ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    platform_user_id: str
    display_name: str
    attributes: _containers.ScalarMap[str, str]
    def __init__(self, platform_user_id: _Optional[str] = ..., display_name: _Optional[str] = ..., attributes: _Optional[_Mapping[str, str]] = ...) -> None: ...

class InboundEvent(_message.Message):
    __slots__ = ("event_id", "platform", "channel_id", "account_id", "sender", "content", "received_at", "metadata")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_ID_FIELD_NUMBER: _ClassVar[int]
    SENDER_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    RECEIVED_AT_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    event_id: str
    platform: str
    channel_id: str
    account_id: str
    sender: UntrustedSender
    content: _common_pb2.Payload
    received_at: _timestamp_pb2.Timestamp
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, event_id: _Optional[str] = ..., platform: _Optional[str] = ..., channel_id: _Optional[str] = ..., account_id: _Optional[str] = ..., sender: _Optional[_Union[UntrustedSender, _Mapping]] = ..., content: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., received_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SpeakerIdentity(_message.Message):
    __slots__ = ("mode", "agent_name", "display_prefix", "bot_account_id")
    MODE_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_PREFIX_FIELD_NUMBER: _ClassVar[int]
    BOT_ACCOUNT_ID_FIELD_NUMBER: _ClassVar[int]
    mode: IdentityMode
    agent_name: str
    display_prefix: str
    bot_account_id: str
    def __init__(self, mode: _Optional[_Union[IdentityMode, str]] = ..., agent_name: _Optional[str] = ..., display_prefix: _Optional[str] = ..., bot_account_id: _Optional[str] = ...) -> None: ...

class OutboundMessage(_message.Message):
    __slots__ = ("message_id", "platform", "channel_id", "account_id", "content", "speaker", "reply_to_event_id")
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    SPEAKER_FIELD_NUMBER: _ClassVar[int]
    REPLY_TO_EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    platform: str
    channel_id: str
    account_id: str
    content: _common_pb2.Payload
    speaker: SpeakerIdentity
    reply_to_event_id: str
    def __init__(self, message_id: _Optional[str] = ..., platform: _Optional[str] = ..., channel_id: _Optional[str] = ..., account_id: _Optional[str] = ..., content: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., speaker: _Optional[_Union[SpeakerIdentity, _Mapping]] = ..., reply_to_event_id: _Optional[str] = ...) -> None: ...

class DeliveryReceipt(_message.Message):
    __slots__ = ("message_id", "delivered", "error")
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    DELIVERED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    delivered: bool
    error: _common_pb2.ErrorInfo
    def __init__(self, message_id: _Optional[str] = ..., delivered: bool = ..., error: _Optional[_Union[_common_pb2.ErrorInfo, _Mapping]] = ...) -> None: ...
