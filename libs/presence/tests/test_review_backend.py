"""ServiceReviewBackend (requisito 39): what the review page reads from the
service and how it changes it. The service and the monitor are fakes; what is
under test is the grouping, the mapping and the single writer lock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import CountingLock

from janus_presence.errors import PresenceError
from janus_presence.models import Evidence, IdentityState, PersonRecord
from janus_presence.monitor import SourceHealth, SourceState
from janus_presence.review_backend import ServiceReviewBackend
from janus_presence.review_pages import SourceRow

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
NO_EMBEDDING = -1


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def make_person(
    person_id: str,
    label: str | None = None,
    state: IdentityState = IdentityState.UNKNOWN,
    snapshot_ref: str | None = "snapshot.enc",
) -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        state=state,
        embedding_ids=[],
        first_seen_at=T0,
        last_seen_at=at(60),
        label=label,
        snapshot_ref=snapshot_ref,
    )


def make_evidence(
    evidence_id: str,
    person_id: str,
    captured_at: datetime,
    hypothesis_person_id: str | None = None,
    confidence: float | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        person_id=person_id,
        source_id="cuarto",
        modality="face",
        hnsw_id=NO_EMBEDDING,
        captured_at=captured_at,
        hypothesis_person_id=hypothesis_person_id,
        hypothesis_confidence=confidence,
    )


class FakeService:
    """Records each call and whether the service lock was held during it."""

    def __init__(self, lock: CountingLock) -> None:
        self._lock = lock
        self.pending: list[Evidence] = []
        self.people: dict[str, PersonRecord] = {}
        self.snapshots: dict[str, bytes] = {}
        self.thumbnails: dict[str, bytes] = {}
        self.thresholds: tuple[float, float] = (1.0, 1.3)
        self.calls: list[tuple] = []
        self.held: list[bool] = []

    def pending_review(self) -> list[Evidence]:
        self._enter("pending_review")
        return list(self.pending)

    def get_person(self, person_id: str) -> PersonRecord | None:
        self._enter("get_person", person_id)
        return self.people.get(person_id)

    def load_snapshot(self, person_id: str) -> bytes | None:
        self._enter("load_snapshot", person_id)
        return self.snapshots.get(person_id)

    def has_evidence_thumbnail(self, evidence_id: str) -> bool:
        return evidence_id in self.thumbnails

    def load_evidence_thumbnail(self, evidence_id: str) -> bytes | None:
        self._enter("load_evidence_thumbnail", evidence_id)
        return self.thumbnails.get(evidence_id)

    def pending_evidence_ids(self, person_id: str) -> list[str]:
        self._enter("pending_evidence_ids", person_id)
        return [item.evidence_id for item in self.pending if item.person_id == person_id]

    def merge_persons(self, source_id: str, target_id: str) -> None:
        self._enter("merge_persons", source_id, target_id)

    def match_thresholds(self) -> tuple[float, float]:
        self._enter("match_thresholds")
        return self.thresholds

    def set_match_thresholds(self, match: float, ambiguous: float) -> None:
        self._enter("set_match_thresholds", match, ambiguous)
        self.thresholds = (match, ambiguous)

    def name_person(self, person_id: str, label: str) -> None:
        self._enter("name_person", person_id, label)

    def set_role(self, person_id: str, role: str) -> None:
        self._enter("set_role", person_id, role)

    def roles(self) -> tuple[str, ...]:
        return ("owner", "family")

    def confirm_evidence(self, evidence_id: str) -> None:
        self._enter("confirm_evidence", evidence_id)

    def reject_evidence(self, evidence_id: str) -> None:
        self._enter("reject_evidence", evidence_id)

    def discard_evidence(self, evidence_id: str) -> None:
        self._enter("discard_evidence", evidence_id)

    def _enter(self, *call: object) -> None:
        self.calls.append(call)
        self.held.append(self._lock.active)


class FakeMonitor:
    def __init__(self) -> None:
        self.report: list[SourceHealth] = []
        self.frames: dict[str, bytes] = {}
        self.frame_requests: list[tuple[str, float]] = []

    def health(self) -> list[SourceHealth]:
        return self.report

    def fresh_frame(self, source_id: str, max_age_s: float) -> bytes | None:
        self.frame_requests.append((source_id, max_age_s))
        return self.frames.get(source_id)


@pytest.fixture
def rig() -> SimpleNamespace:
    lock = CountingLock()
    service = FakeService(lock)
    monitor = FakeMonitor()
    backend = ServiceReviewBackend(service, monitor, lock)
    return SimpleNamespace(lock=lock, service=service, monitor=monitor, backend=backend)


class TestReviewGroups:
    def test_evidence_is_grouped_by_person_newest_group_first(self, rig):
        rig.service.people = {
            "ana": make_person("ana", "Ana", IdentityState.PROVISIONAL),
            "desconocido": make_person("desconocido"),
        }
        rig.service.pending = [
            make_evidence("e1", "desconocido", at(0)),
            make_evidence("e2", "desconocido", at(10)),
            make_evidence("e3", "ana", at(20)),
        ]

        groups = rig.backend.review_groups()

        assert [group.person_id for group in groups] == ["ana", "desconocido"]
        assert [item.evidence_id for item in groups[1].evidence] == ["e2", "e1"]

    def test_a_group_carries_the_person_and_whether_a_photo_is_kept(self, rig):
        rig.service.people = {
            "ana": make_person("ana", "Ana", IdentityState.PROVISIONAL, snapshot_ref=None)
        }
        rig.service.pending = [make_evidence("e1", "ana", at(0))]

        group = rig.backend.review_groups()[0]

        assert group.label == "Ana"
        assert group.state == "provisional"
        assert group.has_snapshot is False
        assert group.last_seen_at == at(60)

    def test_a_person_forgotten_meanwhile_has_no_group(self, rig):
        rig.service.people = {"ana": make_person("ana", "Ana", IdentityState.PROVISIONAL)}
        rig.service.pending = [
            make_evidence("e1", "ana", at(0)),
            make_evidence("e2", "olvidada", at(5)),
        ]

        groups = rig.backend.review_groups()

        assert [group.person_id for group in groups] == ["ana"]

    def test_nothing_pending_is_an_empty_list(self, rig):
        assert rig.backend.review_groups() == []

    def test_reading_the_queue_holds_the_service_lock(self, rig):
        rig.service.people = {"ana": make_person("ana", "Ana", IdentityState.PROVISIONAL)}
        rig.service.pending = [make_evidence("e1", "ana", at(0))]

        rig.backend.review_groups()

        assert rig.service.held
        assert all(rig.service.held)


class TestHypothesis:
    def suspects(self, rig, suspect: PersonRecord | None) -> str | None:
        rig.service.people = {"nueva": make_person("nueva")}
        if suspect is not None:
            rig.service.people[suspect.person_id] = suspect
        rig.service.pending = [make_evidence("e1", "nueva", at(0), "sospechoso", 0.6)]
        return rig.backend.review_groups()[0].evidence[0].hypothesis_label

    def test_a_named_suspect_shows_its_name(self, rig):
        beto = make_person("sospechoso", "Beto", IdentityState.ESTABLISHED)

        assert self.suspects(rig, beto) == "Beto"

    def test_an_unnamed_suspect_is_described_without_a_name(self, rig):
        assert self.suspects(rig, make_person("sospechoso")) == "una persona sin nombre"

    def test_a_suspect_who_no_longer_exists_is_no_hypothesis(self, rig):
        assert self.suspects(rig, None) is None

    def test_evidence_without_a_suspect_has_no_hypothesis(self, rig):
        rig.service.people = {"nueva": make_person("nueva")}
        rig.service.pending = [make_evidence("e1", "nueva", at(0))]

        item = rig.backend.review_groups()[0].evidence[0]

        assert item.hypothesis_label is None
        assert item.hypothesis_confidence is None

    def test_the_confidence_is_passed_through(self, rig):
        beto = make_person("sospechoso", "Beto", IdentityState.ESTABLISHED)
        self.suspects(rig, beto)

        item = rig.backend.review_groups()[0].evidence[0]

        assert item.hypothesis_confidence == 0.6


class TestSuggestionAndThumbnails:
    def test_the_person_most_evidence_points_at_becomes_the_merge_suggestion(self, rig):
        rig.service.people = {
            "nueva": make_person("nueva"),
            "joanfer": make_person("joanfer", "Joanfer", IdentityState.ESTABLISHED),
            "otro": make_person("otro", "Otro", IdentityState.ESTABLISHED),
        }
        rig.service.pending = [
            make_evidence("e1", "nueva", at(0), "joanfer", 0.2),
            make_evidence("e2", "nueva", at(1), "joanfer", 0.3),
            make_evidence("e3", "nueva", at(2), "otro", 0.4),
        ]

        group = rig.backend.review_groups()[0]

        assert group.suggested_person_id == "joanfer"
        assert group.suggested_label == "Joanfer"

    def test_evidence_without_hypotheses_suggests_nothing(self, rig):
        rig.service.people = {"nueva": make_person("nueva")}
        rig.service.pending = [make_evidence("e1", "nueva", at(0))]

        group = rig.backend.review_groups()[0]

        assert group.suggested_person_id is None
        assert group.suggested_label is None

    def test_a_row_knows_whether_it_has_a_thumbnail(self, rig):
        rig.service.people = {"ana": make_person("ana", "Ana", IdentityState.PROVISIONAL)}
        rig.service.pending = [make_evidence("e1", "ana", at(1)), make_evidence("e2", "ana", at(0))]
        rig.service.thumbnails["e1"] = b"jpeg"

        items = rig.backend.review_groups()[0].evidence

        assert [item.has_thumb for item in items] == [True, False]

    def test_the_thumbnail_comes_from_the_service_under_the_lock(self, rig):
        rig.service.thumbnails["e1"] = b"jpeg"

        assert rig.backend.evidence_thumbnail("e1") == b"jpeg"
        assert rig.service.held == [True]


class TestBulkMergeAndSettings:
    def test_a_bulk_decision_is_applied_to_every_pending_row_of_the_person(self, rig):
        rig.service.pending = [
            make_evidence("e1", "ana", at(0)),
            make_evidence("e2", "ana", at(1)),
            make_evidence("e3", "beto", at(2)),
        ]

        rig.backend.resolve_all("ana", "reject")

        assert ("reject_evidence", "e1") in rig.service.calls
        assert ("reject_evidence", "e2") in rig.service.calls
        assert ("reject_evidence", "e3") not in rig.service.calls
        assert all(rig.service.held)

    def test_an_unknown_bulk_decision_changes_nothing(self, rig):
        rig.service.pending = [make_evidence("e1", "ana", at(0))]

        with pytest.raises(PresenceError):
            rig.backend.resolve_all("ana", "erase")

        assert rig.service.calls == []

    def test_merging_delegates_under_the_lock(self, rig):
        rig.backend.merge_persons("nueva", "joanfer")

        assert rig.service.calls == [("merge_persons", "nueva", "joanfer")]
        assert rig.service.held == [True]

    def test_thresholds_are_read_and_written_under_the_lock(self, rig):
        rig.backend.set_match_thresholds(0.8, 1.2)

        assert rig.backend.match_thresholds() == (0.8, 1.2)
        assert rig.service.held == [True, True]


class TestSources:
    def test_health_becomes_one_row_per_source(self, rig):
        rig.monitor.report = [
            SourceHealth(
                "cuarto",
                state=SourceState.UP,
                last_frame_at=T0,
                processing_errors=2,
            ),
            SourceHealth(
                "jardin",
                state=SourceState.DOWN,
                consecutive_failures=4,
                last_error="no frame",
            ),
        ]

        rows = rig.backend.sources()

        assert rows == [
            SourceRow("cuarto", "up", T0, 0, 2, None),
            SourceRow("jardin", "down", None, 4, 0, "no frame"),
        ]

    def test_showing_health_never_waits_for_the_service_lock(self, rig):
        rig.monitor.report = [SourceHealth("cuarto")]

        rig.backend.sources()

        assert rig.lock.entries == 0

    def test_the_live_frame_comes_from_the_monitor_without_the_service_lock(self, rig):
        rig.monitor.frames["cuarto"] = b"jpeg"

        assert rig.backend.camera_frame("cuarto") == b"jpeg"
        assert rig.backend.camera_frame("jardin") is None
        assert rig.lock.entries == 0

    def test_the_live_frame_is_asked_with_a_short_max_age(self, rig):
        rig.backend.camera_frame("cuarto")

        [(source_id, max_age_s)] = rig.monitor.frame_requests
        assert source_id == "cuarto"
        assert 0 < max_age_s <= 0.25


class TestSetRole:
    def test_the_role_is_set_through_the_service_under_the_lock(self, rig):
        rig.backend.set_role("ana", "owner")

        assert rig.service.calls == [("set_role", "ana", "owner")]
        assert rig.service.held == [True]

    def test_the_vocabulary_comes_from_the_service_without_the_lock(self, rig):
        assert rig.backend.roles() == ("owner", "family")
        assert rig.lock.entries == 0


class TestSnapshotAndChanges:
    def test_the_snapshot_comes_from_the_service_under_the_lock(self, rig):
        rig.service.snapshots["ana"] = b"jpeg"

        assert rig.backend.snapshot("ana") == b"jpeg"
        assert rig.service.held == [True]

    def test_a_person_without_a_snapshot_gives_none(self, rig):
        assert rig.backend.snapshot("ana") is None

    def test_naming_delegates_under_the_lock(self, rig):
        rig.backend.name_person("ana", "Ana")

        assert rig.service.calls == [("name_person", "ana", "Ana")]
        assert rig.service.held == [True]

    @pytest.mark.parametrize("action", ["confirm_evidence", "reject_evidence", "discard_evidence"])
    def test_evidence_changes_delegate_under_the_lock(self, rig, action):
        getattr(rig.backend, action)("e1")

        assert rig.service.calls == [(action, "e1")]
        assert rig.service.held == [True]
