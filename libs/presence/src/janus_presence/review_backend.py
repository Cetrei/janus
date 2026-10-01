"""The review page's view of the running service (SPEC.md ampliación,
requisito 39).

`ReviewApp` asks for what it needs through the `ReviewBackend` protocol;
this is the implementation over the real `PresenceService`. Every call into
the service takes the same lock the monitor and the periodic jobs use, since
the service is single writer (see monitor.py). Health is the exception: the
monitor keeps it behind its own small lock, so showing it never waits for a
frame being processed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from janus_presence.errors import PresenceError
from janus_presence.review_pages import EvidenceItem, PersonGroup, SourceRow

if TYPE_CHECKING:
    from janus_presence.models import Evidence
    from janus_presence.monitor import ServiceLock, SourceMonitor
    from janus_presence.service import PresenceService

__all__ = ["ServiceReviewBackend"]

_UNNAMED_HYPOTHESIS = "una persona sin nombre"

# How old a frame may be when the live view asks for one: about ten frames per
# second, however slowly the detector samples.
_LIVE_MAX_AGE_S = 0.1


class ServiceReviewBackend:
    def __init__(
        self, service: PresenceService, monitor: SourceMonitor, service_lock: ServiceLock
    ) -> None:
        self._service = service
        self._monitor = monitor
        self._lock = service_lock

    def review_groups(self) -> list[PersonGroup]:
        """Pending evidence grouped by person, newest first. Listing it counts
        as presenting it to the owner (requisito 29), which is what starts the
        forget clock for whatever is shown here (requisito 34)."""
        with self._lock:
            by_person: dict[str, list[Evidence]] = {}
            for evidence in self._service.pending_review():
                by_person.setdefault(evidence.person_id, []).append(evidence)
            groups = [
                group
                for person_id, items in by_person.items()
                if (group := self._group(person_id, items)) is not None
            ]
        return sorted(groups, key=lambda group: group.evidence[0].captured_at, reverse=True)

    def sources(self) -> list[SourceRow]:
        return [
            SourceRow(
                source_id=health.source_id,
                state=health.state.value,
                last_frame_at=health.last_frame_at,
                consecutive_failures=health.consecutive_failures,
                processing_errors=health.processing_errors,
                last_error=health.last_error,
            )
            for health in self._monitor.health()
        ]

    def snapshot(self, person_id: str) -> bytes | None:
        with self._lock:
            return self._service.load_snapshot(person_id)

    def camera_frame(self, source_id: str) -> bytes | None:
        """A recent frame of a camera for the live view. Like health, it comes
        from the monitor and never waits for the service lock."""
        return self._monitor.fresh_frame(source_id, _LIVE_MAX_AGE_S)

    def evidence_thumbnail(self, evidence_id: str) -> bytes | None:
        with self._lock:
            return self._service.load_evidence_thumbnail(evidence_id)

    def name_person(self, person_id: str, label: str) -> None:
        with self._lock:
            self._service.name_person(person_id, label)

    def set_role(self, person_id: str, role: str) -> None:
        with self._lock:
            self._service.set_role(person_id, role)

    def confirm_evidence(self, evidence_id: str) -> None:
        with self._lock:
            self._service.confirm_evidence(evidence_id)

    def reject_evidence(self, evidence_id: str) -> None:
        with self._lock:
            self._service.reject_evidence(evidence_id)

    def discard_evidence(self, evidence_id: str) -> None:
        with self._lock:
            self._service.discard_evidence(evidence_id)

    def resolve_all(self, person_id: str, decision: str) -> None:
        """Applies one decision to every pending evidence of a person, under a
        single lock hold. The first refusal (an unnamed person cannot be
        confirmed) stops it before anything else changes, because the check is
        about the person and fails on the first item."""
        resolvers: dict[str, Callable[[str], object]] = {
            "confirm": self._service.confirm_evidence,
            "reject": self._service.reject_evidence,
            "discard": self._service.discard_evidence,
        }
        resolve = resolvers.get(decision)
        if resolve is None:
            raise PresenceError(f"Unknown decision '{decision}'")
        with self._lock:
            for evidence_id in self._service.pending_evidence_ids(person_id):
                resolve(evidence_id)

    def merge_persons(self, source_id: str, target_id: str) -> None:
        with self._lock:
            self._service.merge_persons(source_id, target_id)

    def match_thresholds(self) -> tuple[float, float]:
        with self._lock:
            return self._service.match_thresholds()

    def set_match_thresholds(self, match: float, ambiguous: float) -> None:
        with self._lock:
            self._service.set_match_thresholds(match, ambiguous)

    def _group(self, person_id: str, items: list[Evidence]) -> PersonGroup | None:
        """Called with the lock held. A person who was forgotten between the
        query and here has no group."""
        person = self._service.get_person(person_id)
        if person is None:
            return None
        newest_first = sorted(items, key=lambda item: item.captured_at, reverse=True)
        suggested_id, suggested_label = self._suggestion(person_id, newest_first)
        return PersonGroup(
            person_id=person.person_id,
            label=person.label,
            state=person.state.value,
            role=person.role,
            has_snapshot=person.snapshot_ref is not None,
            first_seen_at=person.first_seen_at,
            last_seen_at=person.last_seen_at,
            evidence=tuple(self._item(evidence) for evidence in newest_first),
            suggested_person_id=suggested_id,
            suggested_label=suggested_label,
        )

    def _suggestion(self, person_id: str, items: list[Evidence]) -> tuple[str | None, str | None]:
        """The person most of this group's evidence points at, if any, so the
        page can offer to merge into them."""
        votes = Counter(
            item.hypothesis_person_id
            for item in items
            if item.hypothesis_person_id not in (None, person_id)
        )
        if not votes:
            return None, None
        suggested_id = votes.most_common(1)[0][0]
        suspect = self._service.get_person(suggested_id)
        if suspect is None:
            return None, None
        return suggested_id, suspect.label or _UNNAMED_HYPOTHESIS

    def _item(self, evidence: Evidence) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=evidence.evidence_id,
            captured_at=evidence.captured_at,
            source_id=evidence.source_id,
            hypothesis_label=self._hypothesis_label(evidence),
            hypothesis_confidence=evidence.hypothesis_confidence,
            hypothesis_person_id=evidence.hypothesis_person_id,
            has_thumb=self._service.has_evidence_thumbnail(evidence.evidence_id),
        )

    def _hypothesis_label(self, evidence: Evidence) -> str | None:
        if evidence.hypothesis_person_id is None:
            return None
        suspect = self._service.get_person(evidence.hypothesis_person_id)
        if suspect is None:
            return None
        return suspect.label or _UNNAMED_HYPOTHESIS
