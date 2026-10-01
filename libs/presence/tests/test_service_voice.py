from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import KEY_A, FakeFrameSource, FakeHnswIndex, make_embedding
from janus_biometrics import BiometricsError, PcmAudio, VoiceEmbedding

from janus_presence.errors import PersonNotFoundError, PresenceUnavailableError
from janus_presence.models import IdentityState, PresenceConfig
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore

VOICE_DIM = 256
VOICE_THRESHOLD = 0.5
VOICE_THRESHOLD_AMBIGUOUS = 1.0

_QUALITY_GOOD = 1
_QUALITY_SHORT = 0
_QUALITY_BROKEN = 2


def voice_vector(speaker: int, noise: int = 0) -> list[float]:
    """A speaker is a direction: one-hot at `speaker`. Different speakers are
    orthogonal (squared distance 2 once unit length), the same speaker is
    identical. `noise` leans the vector towards a neighbour dimension, giving
    a small non zero distance for tests that need a confidence below 1."""
    vector = [0.0] * VOICE_DIM
    vector[speaker] = 1.0
    if noise:
        vector[(speaker + 1) % VOICE_DIM] = noise / 100
    return vector


def make_audio(speaker: int, quality: int = _QUALITY_GOOD, noise: int = 0) -> PcmAudio:
    """The fake embedder reads everything it needs from these bytes."""
    return PcmAudio(samples=bytes([speaker, quality, noise]))


class FakeVoiceEmbedder:
    """Stands in for janus_biometrics.VoiceEmbedder: no model, no sherpa."""

    def __init__(self) -> None:
        self.closed = False

    def embed(self, audio: PcmAudio) -> VoiceEmbedding:
        speaker, quality, noise = audio.samples[0], audio.samples[1], audio.samples[2]
        if quality == _QUALITY_BROKEN:
            raise BiometricsError("stream not ready (fake)")
        return VoiceEmbedding(
            embedding=voice_vector(speaker, noise),
            speech_s=3.0 if quality == _QUALITY_GOOD else 0.5,
            quality_ok=quality == _QUALITY_GOOD,
        )

    def close(self) -> None:
        self.closed = True


class FakeFace:
    def __init__(self, embedding: list[float], quality_ok: bool = True) -> None:
        self.embedding = embedding
        self.quality_ok = quality_ok
        self.bbox = None


def face_vector(offset: float = 0.0) -> list[float]:
    """Distance to the all zero face is offset squared."""
    vector = make_embedding(0.0)
    vector[0] = offset
    return vector


def make_service(
    tmp_path: Path,
    fake_index,
    voice: bool = True,
    max_samples_per_person: int = 20,
) -> PresenceService:
    store = PresenceStore(tmp_path / "state", KEY_A)
    return PresenceService(
        store=store,
        index=fake_index,
        model_cache=object(),
        frame_sources={"front-door": FakeFrameSource({"front-door": b"frame"})},
        match_threshold=1.0,
        match_threshold_ambiguous=2.0,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
        max_samples_per_person=max_samples_per_person,
        voice_index=FakeHnswIndex() if voice else None,
        voice_embedder=FakeVoiceEmbedder() if voice else None,
        voice_match_threshold=VOICE_THRESHOLD if voice else None,
        voice_match_threshold_ambiguous=VOICE_THRESHOLD_AMBIGUOUS if voice else None,
    )


def _patch_faces(*faces: FakeFace):
    return patch.object(PresenceService, "_embed", return_value=list(faces))


class TestVoiceConfiguration:
    def test_voice_thresholds_have_no_factory_default(self):
        config = PresenceConfig(match_threshold=0.5, match_threshold_ambiguous=1.0)

        assert config.voice_match_threshold is None
        assert config.voice_match_threshold_ambiguous is None

    def test_config_rejects_one_voice_threshold_without_the_other(self):
        with pytest.raises(ValueError, match="together"):
            PresenceConfig(
                match_threshold=0.5, match_threshold_ambiguous=1.0, voice_match_threshold=0.3
            )

    def test_config_rejects_inverted_voice_thresholds(self):
        with pytest.raises(ValueError, match="greater"):
            PresenceConfig(
                match_threshold=0.5,
                match_threshold_ambiguous=1.0,
                voice_match_threshold=0.6,
                voice_match_threshold_ambiguous=0.6,
            )

    def test_service_rejects_a_voice_index_without_thresholds(self, tmp_path, fake_index):
        with pytest.raises(ValueError, match="required"):
            PresenceService(
                store=PresenceStore(tmp_path / "state", KEY_A),
                index=fake_index,
                model_cache=object(),
                frame_sources={},
                match_threshold=1.0,
                match_threshold_ambiguous=2.0,
                clip_duration_s=15,
                clips_root=tmp_path / "clips",
                clips_max_total_mb=2048,
                unknown_snapshot_retention_s=86_400,
                snapshots_root=tmp_path / "snapshots",
                voice_index=FakeHnswIndex(),
            )

    def test_identify_with_audio_needs_voice_to_be_configured(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, voice=False)

        with pytest.raises(PresenceUnavailableError, match="voice"):
            service.identify(audio=make_audio(1))

    def test_a_voice_setup_that_cannot_load_is_reported_not_swallowed(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        service._voice_embedder = None

        broken = BiometricsError("no sherpa")
        with (
            patch("janus_presence.service.VoiceEmbedder", side_effect=broken),
            pytest.raises(PresenceUnavailableError, match="no sherpa"),
        ):
            service.identify(audio=make_audio(1))

    def test_identify_needs_an_image_or_an_audio(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with pytest.raises(ValueError, match="image, an audio"):
            service.identify()


class TestVoiceIdentification:
    def test_enrolled_voice_is_identified(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person = service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        result = service.identify(audio=make_audio(1))

        assert [c.person_id for c in result.candidates] == [person.person_id]
        assert result.modalities == ["voice"]
        assert result.conflict is False

    def test_another_speaker_matches_nobody(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        result = service.identify(audio=make_audio(2))

        assert result.candidates == []
        assert result.modalities == ["voice"]

    def test_an_utterance_too_short_points_at_nobody(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        result = service.identify(audio=make_audio(1, quality=_QUALITY_SHORT))

        assert result.candidates == []
        assert result.modalities == []

    def test_audio_that_cannot_be_embedded_is_no_match_not_an_error(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        result = service.identify(audio=make_audio(1, quality=_QUALITY_BROKEN))

        assert result.candidates == []

    def test_identify_by_voice_writes_nothing(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])
        persons_before = len(service._store.all_persons())
        size_before = service.status().index_size

        service.identify(audio=make_audio(2))

        assert len(service._store.all_persons()) == persons_before
        assert service.status().index_size == size_before


class TestFusion:
    """requisito 24."""

    def _enroll_ana_with_face_and_voice(self, service):
        with _patch_faces(FakeFace(face_vector(0.0))):
            return service.enroll_known_person("Ana", [b"img"], voice_samples=[make_audio(1)])

    def test_face_and_voice_on_the_same_person_add_up(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        ana = self._enroll_ana_with_face_and_voice(service)

        with _patch_faces(FakeFace(face_vector(0.5))):
            face_only = service.identify(b"img").candidates[0].confidence
        voice_only = service.identify(audio=make_audio(1, noise=50)).candidates[0].confidence
        with _patch_faces(FakeFace(face_vector(0.5))):
            both = service.identify(b"img", audio=make_audio(1, noise=50))

        assert [c.person_id for c in both.candidates] == [ana.person_id]
        assert both.candidates[0].confidence > max(face_only, voice_only)
        assert both.conflict is False
        assert both.modalities == ["face", "voice"]

    def test_face_and_voice_on_different_people_conflict_and_choose_neither(
        self, tmp_path, fake_index
    ):
        service = make_service(tmp_path, fake_index)
        ana = self._enroll_ana_with_face_and_voice(service)
        bob = service.enroll_known_person("Bob", [], voice_samples=[make_audio(2)])

        with _patch_faces(FakeFace(face_vector(0.0))):
            result = service.identify(b"img", audio=make_audio(2))

        assert result.conflict is True
        assert {c.person_id for c in result.candidates} == {ana.person_id, bob.person_id}

    def test_a_face_nobody_knows_does_not_contradict_a_known_voice(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        ana = service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        with _patch_faces(FakeFace(face_vector(50.0))):
            result = service.identify(b"img", audio=make_audio(1))

        assert [c.person_id for c in result.candidates] == [ana.person_id]
        assert result.conflict is False

    def test_two_weak_signals_cannot_pass_the_cap_of_a_provisional_person(
        self, tmp_path, fake_index
    ):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(face_vector(0.0))):
            sighting = service.observe("front-door", b"frame")
        person = service.name_person(sighting.person_id, "Cy")
        assert person.state == IdentityState.PROVISIONAL
        service.enroll_voice(person.person_id, [make_audio(3)])

        with _patch_faces(FakeFace(face_vector(0.0))):
            result = service.identify(b"img", audio=make_audio(3))

        assert result.candidates[0].confidence == pytest.approx(0.7)


class TestVoiceEnrollment:
    def test_voice_ids_are_numbered_apart_from_face_ids(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(face_vector(0.0))):
            person = service.enroll_known_person(
                "Ana", [b"img"], voice_samples=[make_audio(1)]
            )

        store = service._store
        assert store.embeddings_for_person(person.person_id, "face") == [0]
        assert store.embeddings_for_person(person.person_id, "voice") == [0]

    def test_enrolling_needs_at_least_one_usable_sample(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with pytest.raises(ValueError, match="no voice sample was usable"):
            service.enroll_known_person(
                "Ana", [], voice_samples=[make_audio(1, quality=_QUALITY_SHORT)]
            )

    def test_enroll_voice_adds_templates_and_skips_short_ones(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person = service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        added = service.enroll_voice(
            person.person_id, [make_audio(1, noise=10), make_audio(1, quality=_QUALITY_SHORT)]
        )

        assert added == 1
        assert len(service._store.embeddings_for_person(person.person_id, "voice")) == 2

    def test_enroll_voice_never_exceeds_max_samples_per_person(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, max_samples_per_person=2)
        person = service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        extras = [make_audio(1, noise=n) for n in (5, 6, 7)]

        added = service.enroll_voice(person.person_id, extras)

        assert added == 1
        assert len(service._store.embeddings_for_person(person.person_id, "voice")) == 2

    def test_enroll_voice_for_an_unknown_person_id_fails(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        with pytest.raises(PersonNotFoundError):
            service.enroll_voice("missing", [make_audio(1)])

    def test_status_counts_voice_embeddings_in_the_index(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        samples = [make_audio(1), make_audio(1, noise=9)]
        service.enroll_known_person("Ana", [], voice_samples=samples)

        assert service.status().index_size == 2


class TestVoiceLifecycle:
    def test_voice_index_is_rebuilt_at_startup_from_encrypted_samples(self, tmp_path, fake_index):
        first = make_service(tmp_path, fake_index)
        person = first.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        reborn = make_service(tmp_path, FakeHnswIndex())
        result = reborn.identify(audio=make_audio(1))

        assert [c.person_id for c in result.candidates] == [person.person_id]

    def test_forgetting_a_person_removes_their_voice_from_the_index(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person = service.enroll_known_person("Ana", [], voice_samples=[make_audio(1)])

        service.forget_person(person.person_id)

        assert service.identify(audio=make_audio(1)).candidates == []
        assert service._voice_index.search(voice_vector(1)) == []

    def test_closing_the_service_closes_the_voice_index(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        voice_index = service._voice_index

        service.close()

        assert voice_index.closed is True
