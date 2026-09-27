from __future__ import annotations

from datetime import UTC, datetime

import pytest

from janus_presence.models import CameraConfig, PersonRecord, PresenceConfig


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


class TestPersonRecordKnownInvariant:
    """requisito 1, 3: known=True must always carry a label."""

    def test_known_without_label_raises(self):
        with pytest.raises(ValueError):
            PersonRecord(
                person_id="p1",
                known=True,
                embedding_ids=[1],
                first_seen_at=_now(),
                last_seen_at=_now(),
                label=None,
            )

    def test_unknown_without_label_is_valid(self):
        person = PersonRecord(
            person_id="p1",
            known=False,
            embedding_ids=[1],
            first_seen_at=_now(),
            last_seen_at=_now(),
            label=None,
        )
        assert person.known is False
        assert person.label is None

    def test_known_with_label_is_valid(self):
        person = PersonRecord(
            person_id="p1",
            known=True,
            embedding_ids=[1],
            first_seen_at=_now(),
            last_seen_at=_now(),
            label="Joanfer",
        )
        assert person.known is True


class TestPresenceConfigThresholdOrdering:
    """requisito 5: the ambiguous zone must sit above the main threshold."""

    def test_ambiguous_equal_to_threshold_raises(self):
        with pytest.raises(ValueError):
            PresenceConfig(match_threshold=0.5, match_threshold_ambiguous=0.5)

    def test_ambiguous_below_threshold_raises(self):
        with pytest.raises(ValueError):
            PresenceConfig(match_threshold=0.5, match_threshold_ambiguous=0.3)

    def test_ambiguous_above_threshold_is_valid(self):
        config = PresenceConfig(match_threshold=0.5, match_threshold_ambiguous=0.7)
        assert config.match_threshold_ambiguous > config.match_threshold

    def test_defaults_do_not_fix_thresholds(self):
        # Open Questions: no factory default for either threshold, so both
        # are required constructor args (calibration is mandatory, not
        # silently defaulted).
        with pytest.raises(TypeError):
            PresenceConfig()  # type: ignore[call-arg]


class TestCameraConfig:
    def test_defaults_to_local_source(self):
        camera = CameraConfig(camera_id="front-door", label="Front door")
        assert camera.source == "local"
