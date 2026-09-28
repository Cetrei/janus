from __future__ import annotations

import time
import tracemalloc
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

DEFAULT_LATENCY_WARN_MS_FACE = 1500
DEFAULT_LATENCY_WARN_MS_VOICE = 3000


@dataclass(frozen=True)
class BenchResult:
    """Output of one bench() run for one provider (requisito 26).

    `degraded` mirrors what BiometricService is expected to report at
    runtime once bench numbers are available: this module only measures
    and judges against the configured warn threshold, it does not itself
    change BiometricService's behavior -- wiring a real DEGRADED provider
    state into BiometricStatus is the caller's job (service.py), this is
    the measurement the caller's judgment call is based on.
    """

    kind: str  # "face" | "voice"
    provider_id: str
    model_id: str
    samples: int
    latencies_ms: list[float]
    p50_ms: float
    p95_ms: float
    peak_memory_bytes: int
    latency_warn_ms: float
    degraded: bool
    far: float | None = None
    frr: float | None = None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = round(fraction * (len(ordered) - 1))
    return ordered[max(0, min(index, len(ordered) - 1))]


async def bench_verifier(
    kind: str,
    provider_id: str,
    model_id: str,
    run_once: Callable[[], Awaitable[None]],
    iterations: int = 20,
    latency_warn_ms: float | None = None,
    far: float | None = None,
    frr: float | None = None,
) -> BenchResult:
    """Measures end-to-end latency (requisito 26: detection+liveness+
    embedding for face, or trim+features+embedding for voice -- whatever
    `run_once` actually does end to end) and peak memory for one
    provider, over `iterations` calls to `run_once`.

    `run_once` is the caller's responsibility to construct (a closure
    calling verifier.verify(sample, enrollment) with a real or
    representative sample) rather than something this module builds
    itself: bench.py has no opinion on where samples/enrollments come
    from, only on timing and judging what it's given, same separation as
    calibrate() in enrollment.py not owning where impostor samples come
    from.

    `far`/`frr` are optional pass-through fields from a prior calibrate()
    run (requisito 26: "con datos de calibrate, la tasa de falso rechazo
    y de falsa aceptacion resultantes") -- this function does not compute
    them itself, since that requires labeled genuine/impostor samples
    calibrate() already knows how to score, not a repeated concern here.
    """
    if iterations < 1:
        raise ValueError("bench_verifier requires at least 1 iteration")

    warn_ms = latency_warn_ms
    if warn_ms is None:
        warn_ms = DEFAULT_LATENCY_WARN_MS_FACE if kind == "face" else DEFAULT_LATENCY_WARN_MS_VOICE

    latencies_ms: list[float] = []
    tracemalloc.start()
    try:
        for _ in range(iterations):
            start = time.perf_counter()
            await run_once()
            latencies_ms.append((time.perf_counter() - start) * 1000.0)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    p95 = _percentile(latencies_ms, 0.95)
    return BenchResult(
        kind=kind,
        provider_id=provider_id,
        model_id=model_id,
        samples=iterations,
        latencies_ms=latencies_ms,
        p50_ms=_percentile(latencies_ms, 0.50),
        p95_ms=p95,
        peak_memory_bytes=peak,
        latency_warn_ms=warn_ms,
        degraded=p95 > warn_ms,
        far=far,
        frr=frr,
    )


@dataclass(frozen=True)
class BenchReport:
    """Aggregates one or more BenchResult for printing (CLI `bench`
    command, requisito 26). Kept separate from BenchResult itself so a
    report over several sensors/providers has one place to render from."""

    results: list[BenchResult] = field(default_factory=list)

    @property
    def any_degraded(self) -> bool:
        return any(r.degraded for r in self.results)

    def render(self) -> str:
        lines = ["Biometric bench report", "=" * 23]
        for result in self.results:
            status = "DEGRADED" if result.degraded else "OK"
            lines.append(
                f"[{status}] {result.kind}/{result.provider_id}:{result.model_id} "
                f"-- p50={result.p50_ms:.1f}ms p95={result.p95_ms:.1f}ms "
                f"(warn>{result.latency_warn_ms:.0f}ms) "
                f"peak_mem={result.peak_memory_bytes / 1_048_576:.1f}MiB "
                f"n={result.samples}"
            )
            if result.far is not None or result.frr is not None:
                far_str = f"{result.far:.3%}" if result.far is not None else "n/a"
                frr_str = f"{result.frr:.3%}" if result.frr is not None else "n/a"
                lines.append(f"        FAR={far_str} FRR={frr_str}")
        return "\n".join(lines)
