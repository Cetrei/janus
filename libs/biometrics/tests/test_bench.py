from __future__ import annotations

import asyncio

import pytest

from janus_biometrics.bench import (
    DEFAULT_LATENCY_WARN_MS_FACE,
    DEFAULT_LATENCY_WARN_MS_VOICE,
    BenchReport,
    bench_verifier,
)


async def _fast_run() -> None:
    await asyncio.sleep(0)


async def _slow_run() -> None:
    await asyncio.sleep(0.01)


class TestBenchVerifier:
    @pytest.mark.asyncio
    async def test_rejects_zero_iterations(self):
        with pytest.raises(ValueError, match="at least 1"):
            await bench_verifier("face", "local", "model-1", _fast_run, iterations=0)

    @pytest.mark.asyncio
    async def test_reports_latency_percentiles(self):
        result = await bench_verifier("face", "local", "model-1", _fast_run, iterations=10)
        assert result.samples == 10
        assert len(result.latencies_ms) == 10
        assert result.p50_ms <= result.p95_ms

    @pytest.mark.asyncio
    async def test_defaults_face_warn_threshold(self):
        result = await bench_verifier("face", "local", "model-1", _fast_run, iterations=3)
        assert result.latency_warn_ms == DEFAULT_LATENCY_WARN_MS_FACE

    @pytest.mark.asyncio
    async def test_defaults_voice_warn_threshold(self):
        result = await bench_verifier("voice", "local", "model-1", _fast_run, iterations=3)
        assert result.latency_warn_ms == DEFAULT_LATENCY_WARN_MS_VOICE

    @pytest.mark.asyncio
    async def test_not_degraded_when_within_warn_threshold(self):
        result = await bench_verifier(
            "face", "local", "model-1", _fast_run, iterations=5, latency_warn_ms=1000
        )
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_degraded_when_p95_exceeds_warn_threshold(self):
        result = await bench_verifier(
            "face", "local", "model-1", _slow_run, iterations=5, latency_warn_ms=0.001
        )
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_tracks_peak_memory(self):
        async def _allocate() -> None:
            _ = bytearray(1_000_000)
            await asyncio.sleep(0)

        result = await bench_verifier("face", "local", "model-1", _allocate, iterations=3)
        assert result.peak_memory_bytes > 0

    @pytest.mark.asyncio
    async def test_passes_through_far_frr(self):
        result = await bench_verifier(
            "face", "local", "model-1", _fast_run, iterations=3, far=0.01, frr=0.05
        )
        assert result.far == 0.01
        assert result.frr == 0.05


class TestBenchReport:
    @pytest.mark.asyncio
    async def test_any_degraded_true_if_any_result_degraded(self):
        ok_result = await bench_verifier(
            "face", "local", "m", _fast_run, iterations=3, latency_warn_ms=1000
        )
        bad_result = await bench_verifier(
            "face", "local", "m", _slow_run, iterations=3, latency_warn_ms=0.001
        )
        report = BenchReport(results=[ok_result, bad_result])
        assert report.any_degraded is True

    @pytest.mark.asyncio
    async def test_any_degraded_false_when_all_ok(self):
        ok_result = await bench_verifier(
            "face", "local", "m", _fast_run, iterations=3, latency_warn_ms=1000
        )
        report = BenchReport(results=[ok_result])
        assert report.any_degraded is False

    @pytest.mark.asyncio
    async def test_render_includes_status_and_model(self):
        result = await bench_verifier(
            "face", "local", "my-model", _fast_run, iterations=3, latency_warn_ms=1000
        )
        report = BenchReport(results=[result])
        rendered = report.render()
        assert "my-model" in rendered
        assert "OK" in rendered

    @pytest.mark.asyncio
    async def test_render_includes_far_frr_when_present(self):
        result = await bench_verifier(
            "face", "local", "m", _fast_run, iterations=3, far=0.02, frr=0.04
        )
        rendered = BenchReport(results=[result]).render()
        assert "FAR=" in rendered
        assert "FRR=" in rendered
