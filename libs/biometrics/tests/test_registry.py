from __future__ import annotations

import pytest

from janus_biometrics.errors import RemoteProviderNotAcknowledged
from janus_biometrics.providers.null import NullFaceVerifier, NullSpeakerVerifier
from janus_biometrics.registry import ProviderRef, ProviderRegistry


class TestProviderRef:
    def test_parses_name_only(self):
        ref = ProviderRef.parse("null")
        assert ref.name == "null"
        assert ref.variant is None

    def test_parses_name_with_variant(self):
        ref = ProviderRef.parse("local:sface")
        assert ref.name == "local"
        assert ref.variant == "sface"

    def test_dotted_path_is_detected(self):
        ref = ProviderRef.parse("mypackage.mymodule:MyVerifier")
        assert ref.is_dotted_path

    def test_built_in_name_is_not_dotted_path(self):
        ref = ProviderRef.parse("local:sface")
        assert not ref.is_dotted_path


class TestBuiltInResolution:
    def test_resolves_registered_face_factory(self):
        registry = ProviderRegistry()
        registry.register_face_factory("null", NullFaceVerifier)
        verifier = registry.resolve_face("null")
        assert isinstance(verifier, NullFaceVerifier)

    def test_resolves_registered_speaker_factory(self):
        registry = ProviderRegistry()
        registry.register_speaker_factory("null", NullSpeakerVerifier)
        verifier = registry.resolve_speaker("null")
        assert isinstance(verifier, NullSpeakerVerifier)

    def test_unknown_built_in_name_raises(self):
        registry = ProviderRegistry()
        with pytest.raises(KeyError):
            registry.resolve_face("does-not-exist")

    def test_variant_is_passed_to_factory(self):
        received = {}

        class SpyFaceVerifier(NullFaceVerifier):
            def __init__(self, variant=None):
                received["variant"] = variant
                super().__init__(variant=variant)

        registry = ProviderRegistry()
        registry.register_face_factory("local", SpyFaceVerifier)
        registry.resolve_face("local:sface")
        assert received["variant"] == "sface"


class TestRemoteProviderGate:
    def test_rejects_remote_without_acknowledgement(self):
        registry = ProviderRegistry(allow_remote=False, remote_ack=False)
        with pytest.raises(RemoteProviderNotAcknowledged):
            registry.resolve_face("some.remote.module:RemoteVerifier")

    def test_rejects_when_only_allow_remote_is_set(self):
        registry = ProviderRegistry(allow_remote=True, remote_ack=False)
        with pytest.raises(RemoteProviderNotAcknowledged):
            registry.resolve_face("some.remote.module:RemoteVerifier")

    def test_rejects_when_only_remote_ack_is_set(self):
        registry = ProviderRegistry(allow_remote=False, remote_ack=True)
        with pytest.raises(RemoteProviderNotAcknowledged):
            registry.resolve_face("some.remote.module:RemoteVerifier")

    def test_rejection_message_explains_data_leaves_device(self):
        registry = ProviderRegistry(allow_remote=False, remote_ack=False)
        with pytest.raises(RemoteProviderNotAcknowledged) as exc_info:
            registry.resolve_face("some.remote.module:RemoteVerifier")
        assert "off this device" in str(exc_info.value)
