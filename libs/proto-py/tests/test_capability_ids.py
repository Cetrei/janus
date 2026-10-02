import pytest

from janus_proto import capability_ids


def test_should_match_pattern_for_every_reserved_capability():
    for capability_id in capability_ids.ALL_CAPABILITY_IDS:
        assert capability_ids.CAPABILITY_ID_PATTERN.fullmatch(capability_id)


def test_should_list_eleven_reserved_capabilities():
    assert len(capability_ids.ALL_CAPABILITY_IDS) == 11


def test_should_place_every_reserved_capability_in_a_reserved_namespace():
    for capability_id in capability_ids.ALL_CAPABILITY_IDS:
        assert capability_ids.is_reserved_namespace(capability_id)


def test_should_expose_the_exact_namespaces_reserved_to_the_core():
    assert capability_ids.RESERVED_NAMESPACES == {
        "reasoning",
        "execution",
        "channel",
        "gui",
        "vision",
        "voice",
        "memory",
        "janus",
    }


@pytest.mark.parametrize(
    "capability_id",
    ["reasoning", "Reasoning.complete", "1a.b", "a..b", "a.b.", ".a.b", "a.b c", "a.b\n", ""],
)
def test_should_reject_invalid_capability_id(capability_id):
    assert not capability_ids.is_valid_capability_id(capability_id)


@pytest.mark.parametrize("capability_id", ["home.lights.set", "a.b", "x1_y.z2_w.q"])
def test_should_accept_third_party_capability_id(capability_id):
    assert capability_ids.is_valid_capability_id(capability_id)
    assert not capability_ids.is_reserved_namespace(capability_id)


def test_should_raise_when_asking_namespace_of_invalid_id():
    with pytest.raises(ValueError):
        capability_ids.namespace_of("nodots")
