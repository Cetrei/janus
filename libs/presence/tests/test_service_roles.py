"""Role vocabulary (requisito 25, 48): `set_role` only accepts what
`presence.roles` declares, because an automation compares the role exactly."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import KEY_A, FakeFrameSource

from janus_presence.errors import PersonNotFoundError, PresenceError
from janus_presence.models import DEFAULT_ROLES, IdentityState, PersonRecord, PresenceConfig
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore, new_person_id, utcnow


def make_service(tmp_path: Path, fake_index, **overrides) -> PresenceService:
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
        **overrides,
    )


def add_named_person(service: PresenceService) -> str:
    now = utcnow()
    person = PersonRecord(
        person_id=new_person_id(),
        state=IdentityState.PROVISIONAL,
        embedding_ids=[],
        first_seen_at=now,
        last_seen_at=now,
        label="Ana",
        snapshot_ref=None,
    )
    service._store.create_person(person)
    return person.person_id


class TestRoleVocabulary:
    def test_the_default_vocabulary_is_the_one_the_config_declares(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)

        assert service.roles() == DEFAULT_ROLES
        assert tuple(PresenceConfig(1.0, 2.0).roles) == DEFAULT_ROLES

    def test_a_role_of_the_vocabulary_is_saved(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person_id = add_named_person(service)

        service.set_role(person_id, "family")

        assert service.get_person(person_id).role == "family"

    def test_the_role_is_saved_lower_cased_and_trimmed(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person_id = add_named_person(service)

        service.set_role(person_id, "  Owner ")

        assert service.get_person(person_id).role == "owner"

    def test_a_role_outside_the_vocabulary_is_refused_and_nothing_changes(
        self, tmp_path, fake_index
    ):
        service = make_service(tmp_path, fake_index)
        person_id = add_named_person(service)
        service.set_role(person_id, "guest")

        with pytest.raises(PresenceError, match="not in presence.roles"):
            service.set_role(person_id, "onwer")

        assert service.get_person(person_id).role == "guest"

    def test_the_vocabulary_can_be_replaced_by_the_config(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, roles=["Vecino", "dueño"])
        person_id = add_named_person(service)

        service.set_role(person_id, "vecino")

        assert service.roles() == ("vecino", "dueño")
        assert service.get_person(person_id).role == "vecino"
        with pytest.raises(PresenceError):
            service.set_role(person_id, "owner")

    def test_an_empty_vocabulary_refuses_every_role(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, roles=[])
        person_id = add_named_person(service)

        with pytest.raises(PresenceError):
            service.set_role(person_id, "owner")

    def test_a_valid_role_for_a_person_that_does_not_exist_is_not_found(
        self, tmp_path, fake_index
    ):
        service = make_service(tmp_path, fake_index)

        with pytest.raises(PersonNotFoundError):
            service.set_role(new_person_id(), "owner")
