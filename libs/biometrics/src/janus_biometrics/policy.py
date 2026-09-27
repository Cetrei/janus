from __future__ import annotations

import time
from dataclasses import dataclass, field

from janus_biometrics.base import Decision, Liveness

DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_WINDOW_S = 600
DEFAULT_LOCKOUT_S = 900


@dataclass(frozen=True)
class Thresholds:
    """Per-provider/model cosine similarity thresholds (requisito 11)."""

    t_high: float
    t_low: float
    calibration_recommended: bool = True

    def __post_init__(self) -> None:
        if not (0.0 <= self.t_low <= self.t_high <= 1.0):
            raise ValueError("Thresholds require 0 <= t_low <= t_high <= 1")


def decide(
    score: float,
    thresholds: Thresholds,
    liveness: Liveness,
    liveness_mode: str = "required",
) -> Decision:
    """Map a cosine similarity score to a Decision (requisito 11), applying
    liveness policy (requisito 7). `score` never leaves this function's
    caller as part of the result (requisito 16)."""
    base = _base_decision(score, thresholds)
    return _apply_liveness(base, liveness, liveness_mode)


def _base_decision(score: float, thresholds: Thresholds) -> Decision:
    if score >= thresholds.t_high:
        return Decision.HIGH
    if score >= thresholds.t_low:
        return Decision.MEDIUM
    return Decision.LOW


def _apply_liveness(base: Decision, liveness: Liveness, liveness_mode: str) -> Decision:
    if liveness_mode == "off":
        return base
    if liveness != Liveness.FAIL:
        return base
    if liveness_mode == "required":
        return Decision.LOW
    if liveness_mode == "optional" and base == Decision.HIGH:
        return Decision.MEDIUM
    return base


@dataclass
class _AttemptRecord:
    failures: list[float] = field(default_factory=list)
    locked_until: float | None = None


class AttemptLimiter:
    """Failed-attempt limit and lockout per sender (requisito 13)."""

    def __init__(
        self,
        max_failed_attempts: int = DEFAULT_MAX_FAILED_ATTEMPTS,
        lockout_window_s: float = DEFAULT_LOCKOUT_WINDOW_S,
        lockout_s: float = DEFAULT_LOCKOUT_S,
        clock: callable = time.monotonic,
    ) -> None:
        self._max_failed_attempts = max_failed_attempts
        self._lockout_window_s = lockout_window_s
        self._lockout_s = lockout_s
        self._clock = clock
        self._records: dict[str, _AttemptRecord] = {}

    def is_locked(self, sender_id: str) -> bool:
        record = self._records.get(sender_id)
        if record is None or record.locked_until is None:
            return False
        if self._clock() >= record.locked_until:
            record.locked_until = None
            record.failures.clear()
            return False
        return True

    def record_failure(self, sender_id: str) -> bool:
        """Records a failed verification. Returns True if this failure just
        triggered a lockout."""
        now = self._clock()
        record = self._records.setdefault(sender_id, _AttemptRecord())
        record.failures = [t for t in record.failures if now - t <= self._lockout_window_s]
        record.failures.append(now)
        if len(record.failures) >= self._max_failed_attempts:
            record.locked_until = now + self._lockout_s
            return True
        return False

    def record_success(self, sender_id: str) -> None:
        self._records.pop(sender_id, None)
