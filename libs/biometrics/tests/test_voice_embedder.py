from __future__ import annotations

import numpy as np
import pytest

from janus_biometrics import PcmAudio, VoiceEmbedder, VoiceEmbedding, low_level

_SAMPLE_RATE = 16_000
_EMBEDDING_DIM = 256


class _RecordingCache:
    def __init__(self) -> None:
        self.resolved: list[str] = []

    def resolve(self, name: str) -> str:
        self.resolved.append(name)
        return f"/fake/{name}.onnx"


class _FakeExtractor:
    """Stands in for the sherpa-onnx extractor so no model or native library
    is needed: what is under test is the trimming and the quality flag."""

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self.seen_samples = 0

    def embed(self, audio: PcmAudio) -> list[float]:
        self.seen_samples = len(audio.samples) // 2
        return [0.5] * _EMBEDDING_DIM


@pytest.fixture(autouse=True)
def fake_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(low_level, "SherpaWeSpeakerExtractor", _FakeExtractor)


def _speech(seconds: float, amplitude: int = 8000) -> np.ndarray:
    return np.full(int(seconds * _SAMPLE_RATE), amplitude, dtype=np.int16)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * _SAMPLE_RATE), dtype=np.int16)


def _audio(*parts: np.ndarray) -> PcmAudio:
    return PcmAudio(samples=np.concatenate(parts).tobytes())


def test_should_flag_quality_ok_when_speech_reaches_the_minimum() -> None:
    embedder = VoiceEmbedder(_RecordingCache())

    result = embedder.embed(_audio(_speech(3.0)))

    assert result.quality_ok is True
    assert result.speech_s == pytest.approx(3.0)
    assert len(result.embedding) == _EMBEDDING_DIM


def test_should_still_return_an_embedding_flagged_low_quality_when_speech_is_short() -> None:
    embedder = VoiceEmbedder(_RecordingCache())

    result = embedder.embed(_audio(_speech(1.0)))

    assert result.quality_ok is False
    assert result.speech_s == pytest.approx(1.0)
    assert len(result.embedding) == _EMBEDDING_DIM


def test_should_measure_speech_after_trimming_leading_and_trailing_silence() -> None:
    embedder = VoiceEmbedder(_RecordingCache())

    result = embedder.embed(_audio(_silence(1.0), _speech(3.0), _silence(1.0)))

    assert result.speech_s == pytest.approx(3.0)
    assert result.quality_ok is True


def test_should_honour_a_custom_minimum_speech_duration() -> None:
    embedder = VoiceEmbedder(_RecordingCache(), min_speech_s=0.5)

    result = embedder.embed(_audio(_speech(1.0)))

    assert result.quality_ok is True


def test_should_resolve_the_model_once_at_construction_not_per_utterance() -> None:
    cache = _RecordingCache()
    embedder = VoiceEmbedder(cache)

    embedder.embed(_audio(_speech(3.0)))
    embedder.embed(_audio(_speech(3.0)))

    assert cache.resolved == ["wespeaker"]


def test_should_refuse_to_embed_after_close() -> None:
    embedder = VoiceEmbedder(_RecordingCache())
    embedder.close()

    with pytest.raises(RuntimeError, match="closed"):
        embedder.embed(_audio(_speech(3.0)))


def test_extract_voice_embedding_should_match_the_reusable_embedder() -> None:
    audio = _audio(_speech(3.0))

    one_shot = low_level.extract_voice_embedding(audio, _RecordingCache())

    assert one_shot == VoiceEmbedder(_RecordingCache()).embed(audio)


def test_voice_embedding_should_reject_a_wrong_dimension() -> None:
    with pytest.raises(ValueError, match="256"):
        VoiceEmbedding(embedding=[0.0] * 128, speech_s=3.0, quality_ok=True)
