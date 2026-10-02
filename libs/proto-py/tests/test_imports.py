import importlib

import pytest

import janus_proto
from janus_proto.enums import ENUM_ALIASES

GENERATED_MODULES = [
    "common",
    "semantic",
    "capability",
    "task",
    "session",
    "channel",
    "spoke",
    "gateway",
]


@pytest.mark.parametrize("name", GENERATED_MODULES)
def test_should_import_generated_message_module(name):
    module = importlib.import_module(f"janus_proto.v1.{name}_pb2")

    assert module.DESCRIPTOR.package == "janus_proto.v1"


@pytest.mark.parametrize("name", GENERATED_MODULES)
def test_should_import_generated_grpc_module(name):
    importlib.import_module(f"janus_proto.v1.{name}_pb2_grpc")


@pytest.mark.parametrize("name", janus_proto.__all__)
def test_should_expose_every_name_in_all(name):
    assert hasattr(janus_proto, name)


@pytest.mark.parametrize("name", sorted(ENUM_ALIASES))
def test_should_alias_every_enum_with_matching_values(name):
    alias, wrapper = ENUM_ALIASES[name]

    assert {member.value for member in alias} == set(wrapper.values())
    assert alias.UNSPECIFIED == 0


def test_should_compare_alias_members_with_generated_constants():
    assert janus_proto.EventKind.TERMINAL == 3
    assert janus_proto.ResponseStatus.FAILED == 2
    assert janus_proto.CachePolicyKind.NONE == 1


def test_should_accept_alias_members_in_message_fields():
    event = janus_proto.SemanticEvent(kind=janus_proto.EventKind.PARTIAL)

    assert event.kind == janus_proto.EventKind.PARTIAL
