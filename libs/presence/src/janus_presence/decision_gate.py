from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["DecisionGate", "NoulAnswer", "NoulQuestion"]


@dataclass(frozen=True)
class NoulQuestion:
    """Question sent to libs/decision (spec-19) asking whether a sighting
    that the deterministic layer did NOT already clip (requisito 14) is
    worth recording anyway. `first_seen` is included explicitly so the
    decision model does not redo work the deterministic layer already
    covers (requisito 15)."""

    prompt: str
    person_id: str
    known: bool
    first_seen: bool
    camera_id: str
    confidence: float


@dataclass(frozen=True)
class NoulAnswer:
    value: bool
    confidence: float


class DecisionModelPort(Protocol):
    """Shape janus_presence expects from libs/decision (spec-19). Not
    implemented here: janus_presence takes this as a dependency-injected
    port, same inversion-of-dependency pattern as FrameSource, so it never
    imports libs/decision directly."""

    def ask(self, question: NoulQuestion) -> NoulAnswer: ...


class DecisionGate:
    """Wraps the optional decision-model layer (requisito 15,
    `presence.decision_model_enabled`, default False until measured).

    This can only ever *add* clips on top of what the deterministic layer
    (requisito 14) already recorded for `first_seen=True` sightings: it is
    only ever consulted for sightings the deterministic layer did not
    already clip, so it can never suppress the one clip that matters most.
    """

    def __init__(
        self,
        port: DecisionModelPort,
        confidence_threshold: float = 0.85,
    ) -> None:
        self._port = port
        self._confidence_threshold = confidence_threshold

    def should_record_clip(self, question: NoulQuestion) -> bool:
        answer = self._port.ask(question)
        return answer.value and answer.confidence >= self._confidence_threshold
