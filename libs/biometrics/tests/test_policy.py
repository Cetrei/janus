from __future__ import annotations

import pytest

from janus_biometrics.base import Decision, Liveness
from janus_biometrics.policy import AttemptLimiter, Thresholds, decide


@pytest.fixture
def thresholds() -> Thresholds:
    return Thresholds(t_high=0.8, t_low=0.5)


class TestDecide:
    def test_score_above_high_is_high(self, thresholds):
        result = decide(0.9, thresholds, Liveness.PASS)
        assert result == Decision.HIGH

    def test_score_between_thresholds_is_medium(self, thresholds):
        result = decide(0.65, thresholds, Liveness.PASS)
        assert result == Decision.MEDIUM

    def test_score_below_low_is_low(self, thresholds):
        result = decide(0.2, thresholds, Liveness.PASS)
        assert result == Decision.LOW

    def test_score_at_high_boundary_is_high(self, thresholds):
        result = decide(0.8, thresholds, Liveness.PASS)
        assert result == Decision.HIGH

    def test_score_at_low_boundary_is_medium(self, thresholds):
        result = decide(0.5, thresholds, Liveness.PASS)
        assert result == Decision.MEDIUM


class TestLivenessRequired:
    def test_liveness_fail_forces_low_even_with_high_score(self, thresholds):
        result = decide(0.99, thresholds, Liveness.FAIL, liveness_mode="required")
        assert result == Decision.LOW

    def test_liveness_pass_does_not_change_decision(self, thresholds):
        result = decide(0.9, thresholds, Liveness.PASS, liveness_mode="required")
        assert result == Decision.HIGH


class TestLivenessOptional:
    def test_liveness_fail_degrades_high_to_medium(self, thresholds):
        result = decide(0.99, thresholds, Liveness.FAIL, liveness_mode="optional")
        assert result == Decision.MEDIUM

    def test_liveness_fail_does_not_degrade_medium(self, thresholds):
        result = decide(0.6, thresholds, Liveness.FAIL, liveness_mode="optional")
        assert result == Decision.MEDIUM


class TestLivenessOff:
    def test_liveness_fail_is_ignored(self, thresholds):
        result = decide(0.9, thresholds, Liveness.FAIL, liveness_mode="off")
        assert result == Decision.HIGH


class TestThresholdsValidation:
    def test_rejects_low_above_high(self):
        with pytest.raises(ValueError):
            Thresholds(t_high=0.5, t_low=0.8)

    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            Thresholds(t_high=1.5, t_low=0.5)


class TestAttemptLimiter:
    def test_not_locked_before_reaching_max_attempts(self, fake_clock):
        limiter = AttemptLimiter(max_failed_attempts=3, clock=fake_clock)
        limiter.record_failure("sender-1")
        limiter.record_failure("sender-1")
        assert not limiter.is_locked("sender-1")

    def test_locks_after_max_failed_attempts(self, fake_clock):
        limiter = AttemptLimiter(max_failed_attempts=3, clock=fake_clock)
        limiter.record_failure("sender-1")
        limiter.record_failure("sender-1")
        triggered = limiter.record_failure("sender-1")
        assert triggered
        assert limiter.is_locked("sender-1")

    def test_lockout_expires_after_lockout_window(self, fake_clock):
        limiter = AttemptLimiter(max_failed_attempts=1, lockout_s=100, clock=fake_clock)
        limiter.record_failure("sender-1")
        assert limiter.is_locked("sender-1")
        fake_clock.advance(101)
        assert not limiter.is_locked("sender-1")

    def test_failures_outside_window_do_not_accumulate(self, fake_clock):
        limiter = AttemptLimiter(max_failed_attempts=3, lockout_window_s=60, clock=fake_clock)
        limiter.record_failure("sender-1")
        fake_clock.advance(61)
        limiter.record_failure("sender-1")
        limiter.record_failure("sender-1")
        assert not limiter.is_locked("sender-1")

    def test_success_clears_failure_history(self, fake_clock):
        limiter = AttemptLimiter(max_failed_attempts=3, clock=fake_clock)
        limiter.record_failure("sender-1")
        limiter.record_failure("sender-1")
        limiter.record_success("sender-1")
        limiter.record_failure("sender-1")
        limiter.record_failure("sender-1")
        assert not limiter.is_locked("sender-1")

    def test_different_senders_are_independent(self, fake_clock):
        limiter = AttemptLimiter(max_failed_attempts=1, clock=fake_clock)
        limiter.record_failure("sender-1")
        assert limiter.is_locked("sender-1")
        assert not limiter.is_locked("sender-2")
