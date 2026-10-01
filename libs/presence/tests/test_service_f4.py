"""F4 wiring in PresenceService: visit callbacks (requisito 30) and snapshot
expiry (requisito 12). Detection is patched, as in test_service_f2.py, so no
ONNX models are needed."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import KEY_A, FakeFrameSource, make_embedding

from janus_presence.models import Visit
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore, utcnow

SOURCE = "front-door"
VISIT_GAP_S = 30
SNAPSHOT_RETENTION_S = 3600


class FakeFace:
    def __init__(self, embedding: list[float], quality_ok: bool = True) -> None:
        self.embedding = embedding
        self.quality_ok = quality_ok
        self.bbox = None


def make_service(tmp_path: Path, fake_index) -> PresenceService:
    return PresenceService(
        store=PresenceStore(tmp_path / "state", KEY_A),
        index=fake_index,
        model_cache=object(),
        frame_sources={SOURCE: FakeFrameSource({SOURCE: b"frame"})},
        match_threshold=1.0,
        match_threshold_ambiguous=2.0,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=SNAPSHOT_RETENTION_S,
        snapshots_root=tmp_path / "snapshots",
        visit_gap_s=VISIT_GAP_S,
    )


def _patch_faces(*faces: FakeFace):
    return patch.object(PresenceService, "_embed", return_value=list(faces))


def after_retention() -> datetime:
    return utcnow() + timedelta(seconds=SNAPSHOT_RETENTION_S + 5)


class TestVisitCallbacks:
    def test_started_fires_once_however_many_consecutive_sightings(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        started: list[Visit] = []
        service.on_visit_started(started.append)

        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.observe(SOURCE, b"frame")
            service.observe(SOURCE, b"frame")
            service.observe(SOURCE, b"frame")

        assert len(started) == 1
        assert started[0].person_id == first.person_id
        assert started[0].source_id == SOURCE
        assert started[0].ended_at is None

    def test_ended_fires_when_the_gap_has_passed_and_not_before(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        ended: list[Visit] = []
        service.on_visit_ended(ended.append)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe(SOURCE, b"frame")

        service.close_stale_visits(now=utcnow() + timedelta(seconds=VISIT_GAP_S - 5))
        assert ended == []

        service.close_stale_visits(now=utcnow() + timedelta(seconds=VISIT_GAP_S + 5))
        assert len(ended) == 1
        assert ended[0].ended_at == ended[0].last_seen_at

    def test_a_closed_visit_is_not_announced_twice(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        ended: list[Visit] = []
        service.on_visit_ended(ended.append)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe(SOURCE, b"frame")
        later = utcnow() + timedelta(seconds=VISIT_GAP_S + 5)

        service.close_stale_visits(now=later)
        service.close_stale_visits(now=later)

        assert len(ended) == 1

    def test_returning_after_the_gap_ends_the_old_visit_and_starts_a_new_one(
        self, tmp_path, fake_index
    ):
        service = make_service(tmp_path, fake_index)
        started: list[Visit] = []
        ended: list[Visit] = []
        service.on_visit_started(started.append)
        service.on_visit_ended(ended.append)

        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe(SOURCE, b"frame")
            stale = service._store.open_visits()[0]
            service._store.update_visit(
                Visit(
                    visit_id=stale.visit_id,
                    person_id=stale.person_id,
                    source_id=stale.source_id,
                    started_at=stale.started_at - timedelta(seconds=600),
                    last_seen_at=stale.last_seen_at - timedelta(seconds=600),
                )
            )
            service.observe(SOURCE, b"frame")

        assert len(started) == 2
        assert len(ended) == 1
        assert ended[0].visit_id == started[0].visit_id

    def test_no_event_is_delivered_when_the_transaction_rolls_back(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        started: list[Visit] = []
        service.on_visit_started(started.append)
        real_touch_visit = service._touch_visit

        def touch_visit_then_fail(*args):
            real_touch_visit(*args)  # queues visit_started, then the write fails
            raise RuntimeError("boom")

        with (
            _patch_faces(FakeFace(make_embedding(0.0))),
            patch.object(service, "_touch_visit", side_effect=touch_visit_then_fail),
            pytest.raises(RuntimeError),
        ):
            service.observe(SOURCE, b"frame")

        assert started == []
        assert service._store.open_visits() == []


class TestExpireSnapshots:
    def _unknown_with_snapshot(self, service: PresenceService) -> str:
        with _patch_faces(FakeFace(make_embedding(0.0))):
            return service.observe(SOURCE, b"frame").person_id

    def test_a_snapshot_inside_the_retention_window_is_kept(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person_id = self._unknown_with_snapshot(service)

        expired = service.expire_snapshots(now=utcnow() + timedelta(seconds=60))

        assert expired == []
        assert service._store.load_snapshot(person_id) == b"frame"

    def test_an_old_snapshot_is_deleted_but_the_person_is_kept(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person_id = self._unknown_with_snapshot(service)
        snapshot_path = Path(service._store.get_person(person_id).snapshot_ref)

        expired = service.expire_snapshots(now=after_retention())

        person = service._store.get_person(person_id)
        assert expired == [person_id]
        assert person is not None
        assert person.snapshot_ref is None
        assert not snapshot_path.exists()
        assert person.embedding_ids

    def test_expiring_twice_is_a_no_op(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        self._unknown_with_snapshot(service)
        later = after_retention()

        service.expire_snapshots(now=later)

        assert service.expire_snapshots(now=later) == []

    def test_a_person_still_recognised_after_the_snapshot_expired(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        person_id = self._unknown_with_snapshot(service)
        service.expire_snapshots(now=after_retention())

        with _patch_faces(FakeFace(make_embedding(0.0))):
            again = service.observe(SOURCE, b"frame")

        assert again.person_id == person_id
