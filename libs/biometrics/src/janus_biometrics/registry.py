from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from janus_biometrics.errors import RemoteProviderNotAcknowledged

if TYPE_CHECKING:
    from janus_biometrics.base import FaceVerifier, SpeakerVerifier


@dataclass(frozen=True)
class ProviderRef:
    """Parsed provider reference: 'name' or 'name:variant'."""

    name: str
    variant: str | None = None

    @classmethod
    def parse(cls, raw: str) -> ProviderRef:
        if ":" in raw:
            name, variant = raw.split(":", 1)
            return cls(name=name, variant=variant)
        return cls(name=raw)

    @property
    def is_dotted_path(self) -> bool:
        return "." in self.name


class ProviderRegistry:
    """Resolves provider references to FaceVerifier / SpeakerVerifier instances.

    Built-in factory providers (local:sface, local:wespeaker-resnet34, null)
    are registered by name. Third-party or remote providers are resolved by
    dotted path (package.module:Class) and gated behind explicit
    acknowledgement (requisito 4).
    """

    def __init__(self, allow_remote: bool = False, remote_ack: bool = False) -> None:
        self._allow_remote = allow_remote
        self._remote_ack = remote_ack
        self._face_factories: dict[str, type[FaceVerifier]] = {}
        self._speaker_factories: dict[str, type[SpeakerVerifier]] = {}

    def register_face_factory(self, name: str, factory: type[FaceVerifier]) -> None:
        self._face_factories[name] = factory

    def register_speaker_factory(self, name: str, factory: type[SpeakerVerifier]) -> None:
        self._speaker_factories[name] = factory

    def resolve_face(self, raw_ref: str, **kwargs: object) -> FaceVerifier:
        return self._resolve(raw_ref, self._face_factories, **kwargs)

    def resolve_speaker(self, raw_ref: str, **kwargs: object) -> SpeakerVerifier:
        return self._resolve(raw_ref, self._speaker_factories, **kwargs)

    def _resolve(
        self,
        raw_ref: str,
        factories: dict[str, type],
        **kwargs: object,
    ) -> object:
        ref = ProviderRef.parse(raw_ref)
        if ref.is_dotted_path:
            return self._resolve_remote(raw_ref, ref, **kwargs)
        factory = factories.get(ref.name)
        if factory is None:
            raise KeyError(f"Unknown built-in provider '{ref.name}'")
        return factory(variant=ref.variant, **kwargs)

    def _resolve_remote(self, raw_ref: str, ref: ProviderRef, **kwargs: object) -> object:
        if not (self._allow_remote and self._remote_ack):
            raise RemoteProviderNotAcknowledged(raw_ref)
        module_path, _, class_name = ref.name.partition(":")
        module = importlib.import_module(module_path)
        provider_cls = getattr(module, class_name)
        return provider_cls(**kwargs)
