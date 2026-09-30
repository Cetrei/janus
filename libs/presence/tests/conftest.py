from __future__ import annotations

from pathlib import Path

import pytest

from janus_presence.decision_gate import DecisionGate, NoulAnswer, NoulQuestion
from janus_presence.errors import PresenceUnavailableError
from janus_presence.frame_source import FrameSource

KEY_A = b"a" * 32
EMBEDDING_DIM = 128


def make_embedding(seed: float) -> list[float]:
    """A deterministic 128-dim vector, distinct per `seed`, for synthetic
    match/no-match distances (SPEC.md Testing Requirements: "umbral de
    match con distancias sintéticas")."""
    return [seed] * EMBEDDING_DIM


class FakeHnswIndex:
    """In-memory stand-in for PresenceIndex, so unit tests for
    PresenceService and the match threshold don't need vendor/hnsw
    compiled (SPEC.md: "FrameSource falso para pruebas deterministas sin
    cámara real" — same principle applied to the index)."""

    def __init__(self) -> None:
        self._vectors: dict[int, list[float]] = {}
        self.closed = False

    def insert(self, hnsw_id: int, embedding: list[float]) -> None:
        self._vectors[hnsw_id] = list(embedding)

    def remove(self, hnsw_id: int) -> None:
        self._vectors.pop(hnsw_id, None)

    def search(self, embedding: list[float], k: int = 5) -> list[tuple[int, float]]:
        if not self._vectors:
            return []
        distances = [
            (hnsw_id, _squared_distance(embedding, vector))
            for hnsw_id, vector in self._vectors.items()
        ]
        distances.sort(key=lambda pair: pair[1])
        return distances[:k]

    def close(self) -> None:
        self.closed = True


def _squared_distance(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))


class FailingHnswIndex:
    """Simulates hnsw-c failing to load (SPEC.md Edge Cases: "hnsw-c (.so)
    ausente o no carga" -> PresenceUnavailableError, never a crash)."""

    def __init__(self, *args, **kwargs) -> None:
        raise PresenceUnavailableError("hnsw-c", "native extension failed to import (fake)")


class FakeFrameSource(FrameSource):
    """Deterministic FrameSource for tests without a real camera (SPEC.md
    Testing Requirements)."""

    def __init__(self, frames: dict[str, bytes] | None = None) -> None:
        self._frames = frames or {}

    def capture_frame(self, camera_id: str) -> bytes:
        frame = self._frames.get(camera_id)
        if frame is None:
            raise PresenceUnavailableError(f"camera:{camera_id}", "no fake frame configured")
        return frame


class FakeClock:
    """A clock the test moves by hand, so scheduling and backoff are tested
    without sleeping."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class CountingLock:
    """Stands in for the service lock: records how many times it was taken and
    whether it is held right now."""

    def __init__(self) -> None:
        self.entries = 0
        self.active = False

    def __enter__(self) -> CountingLock:
        self.entries += 1
        self.active = True
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.active = False


class FakeDecisionPort:
    """Deterministic decision-model port: the test sets the answer to
    return (SPEC.md requisito 15)."""

    def __init__(self, value: bool = False, confidence: float = 1.0) -> None:
        self.value = value
        self.confidence = confidence
        self.questions: list[NoulQuestion] = []

    def ask(self, question: NoulQuestion) -> NoulAnswer:
        self.questions.append(question)
        return NoulAnswer(value=self.value, confidence=self.confidence)


def make_decision_gate(value: bool = False, confidence: float = 1.0) -> DecisionGate:
    return DecisionGate(FakeDecisionPort(value=value, confidence=confidence))


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def fake_index() -> FakeHnswIndex:
    return FakeHnswIndex()


@pytest.fixture
def fake_ffmpeg(tmp_path: Path) -> str:
    """A stand-in `ffmpeg` executable that copies its stdin into the file
    named by its last argument, which is where ClipRecorder puts the output
    path. It lets tests exercise the real spawn + pipe + writer thread path
    without ffmpeg installed. POSIX only (it is a shell script)."""
    script = tmp_path / "fake-ffmpeg"
    script.write_text('#!/bin/sh\nfor last; do :; done\ncat > "$last"\n')
    script.chmod(0o755)
    return str(script)
