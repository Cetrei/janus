"""local:wespeaker-resnet34 -- WeSpeaker ResNet34 speaker verification
(requisito 9).

STATUS: UNBLOCKED (2026-09-27, Architect decision -- see AGENT.md and
spec-18's Open Questions). The fbank-frontend Open Question ("evaluar
speakeronnx ... o kaldi-native-fbank, y confirmar wheels de aarch64 y de
Windows") is resolved in favor of `sherpa-onnx` (k2-fsa/Next-gen Kaldi,
Apache-2.0, PyPI extra `voice` in this package's pyproject.toml): mature,
wheels confirmed for manylinux2014_x86_64, manylinux2014_aarch64
(Raspberry Pi) and Windows, solves fbank extraction AND ONNX inference in
one package (unlike kaldi-native-fbank alone, which only does the
frontend), and distributes the exact wespeaker ResNet34 model this spec
already named. Rejected `speakeronnx`: a single-maintainer 0.0.x
pre-release, an unacceptable stability risk for a service meant to run
indefinitely on a Raspberry Pi.

WeSpeakerVerifier implements the full SpeakerVerifier contract:
normalization to 16kHz mono (PcmAudio's own contract already guarantees
this at construction, see base.py), silence trimming, the requisito-9
minimum-speech-duration gate (too_short), embedding via an injected
`feature_extractor`, cosine similarity against the enrollment centroid,
and policy.decide() for the HIGH/MEDIUM/LOW/INCONCLUSIVE mapping (unlike
providers/sface.py's own hardcoded-threshold shortcut, already flagged
separately as a Debugger finding -- this class does NOT repeat that
shortcut, it takes Thresholds directly).

`feature_extractor` stays a `WeSpeakerFeatureExtractor` Protocol (embed
PcmAudio -> list[float], 256-dim per spec-18's "Hechos verificados"), the
same injection pattern enrollment.py's VoiceFeatureExtractor uses -- kept
even after unblocking so tests can exercise WeSpeakerVerifier with a fake
extractor (test_wespeaker.py) without a real ONNX session.
`SherpaWeSpeakerExtractor` below is the real implementation of that
Protocol, using sherpa-onnx.

RESOLVED 2026-09-28 (Implementer): the wespeaker ResNet34 .onnx
(wespeaker_en_voxceleb_resnet34.onnx) was downloaded directly from
sherpa-onnx's own release
(https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models),
sha256 computed locally, and further verified by actually loading it
with sherpa_onnx.SpeakerEmbeddingExtractor and confirming 256-dim output
-- see models.yaml's `wespeaker` entry (now a real `url` + verified
`sha256`, no longer a template) and NOTICE for the license attribution
(CC BY 4.0, VoxCeleb).

`WeSpeakerProvider` below is the ProviderRegistry-facing wrapper that
resolves that models.yaml entry via a ModelCache and builds a real
SherpaWeSpeakerExtractor lazily, the voice counterpart of
providers/sface.py's SFaceFaceVerifier -- this is the class registered
under "local" for voice (see registry wiring), while WeSpeakerVerifier
itself stays reachable directly for tests and manual_camera_check.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from janus_biometrics import _face_pipeline as pipeline
from janus_biometrics.base import (
    BiometricResult,
    Decision,
    Enrollment,
    Liveness,
    PcmAudio,
    SpeakerVerifier,
)
from janus_biometrics.errors import BiometricsError, ModelMismatch
from janus_biometrics.models import ModelCache
from janus_biometrics.policy import Thresholds, decide

_PROVIDER_ID = "local"
_MODEL_ID = "wespeaker-resnet34-v1"
_MIN_SPEECH_S_DEFAULT = 2.5  # requisito 9's verification-time floor, distinct
# from enrollment.py's MIN_VOICE_UTTERANCE_S (3.0s, enrollment-time only)
_EXPECTED_EMBEDDING_DIM = 256  # spec-18 "Hechos verificados": wespeaker-resnet34 is 256-dim


class WeSpeakerFeatureExtractor(Protocol):
    """Turns normalized PcmAudio into a 256-dim WeSpeaker embedding: fbank
    (80-band, requisito 9) frontend + ONNX ResNet34 inference. Kept as a
    Protocol (rather than importing SherpaWeSpeakerExtractor directly into
    WeSpeakerVerifier) so tests can inject a fake extractor without a real
    ONNX session -- same shape enrollment.py's VoiceFeatureExtractor uses.
    """

    def embed(self, audio: PcmAudio) -> list[float]: ...


class SherpaWeSpeakerExtractor:
    """Real WeSpeakerFeatureExtractor backed by sherpa-onnx's
    SpeakerEmbeddingExtractor (requires the `voice` extra: sherpa-onnx).

    sherpa-onnx's Python API (confirmed against its own
    python-api-examples/speaker-identification.py): construct a
    SpeakerEmbeddingExtractorConfig pointing at the .onnx model, open a
    stream per utterance, feed it float32 samples normalized to [-1, 1]
    (PcmAudio's int16 samples are converted here, not by the caller),
    mark the stream finished, then compute() once is_ready() -- this
    mirrors that reference usage exactly rather than guessing at the API
    shape.
    """

    def __init__(self, model_path: Path | str, num_threads: int = 1) -> None:
        # Local import: sherpa-onnx is the optional `voice` extra, not a
        # hard dependency of janus_biometrics -- importing this module
        # must not require it; only constructing this class does.
        try:
            import sherpa_onnx
        except ImportError as exc:
            # Keep the real cause in the message: a package that is installed
            # but fails to import (broken native library, ABI or shared-lib
            # clash) is a different problem from one that is missing, and
            # "not installed" alone sent the operator down the wrong path.
            raise BiometricsError(
                f"sherpa-onnx could not be imported: {exc!r}. If the package is missing, "
                "install it with `uv sync --extra voice`; if it is installed, this is a "
                "native library or version problem and the cause is the error above."
            ) from exc

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path),
            num_threads=num_threads,
            provider="cpu",
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        if self._extractor.dim != _EXPECTED_EMBEDDING_DIM:
            raise BiometricsError(
                f"Model at {model_path} produces {self._extractor.dim}-dim embeddings, "
                f"expected {_EXPECTED_EMBEDDING_DIM} (wespeaker-resnet34). "
                "Wrong model file, or a different wespeaker variant."
            )

    def embed(self, audio: PcmAudio) -> list[float]:
        import numpy as np

        samples_int16 = np.frombuffer(audio.samples, dtype=np.int16)
        samples_f32 = samples_int16.astype(np.float32) / 32768.0

        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=audio.sample_rate, waveform=samples_f32)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            # Should not happen once the caller's too_short gate has
            # already run (WeSpeakerVerifier.verify checks duration before
            # calling embed()), but fail loudly rather than returning a
            # meaningless embedding if it ever does.
            raise BiometricsError(
                "sherpa-onnx SpeakerEmbeddingExtractor stream not ready "
                "(insufficient audio after silence trimming)"
            )
        embedding = self._extractor.compute(stream)
        return list(embedding)


def _trim_silence(audio: PcmAudio, energy_threshold: float = 0.01) -> PcmAudio:
    """Trims leading/trailing near-silence (requisito 9) by simple energy
    thresholding on 16-bit PCM samples. Deliberately simple (no VAD model):
    this is a coarse pre-filter before the minimum-speech-duration check,
    not a precision voice-activity detector -- a real VAD model would be
    yet another dependency choice, and requisito 9 does not ask for one."""
    import numpy as np

    samples = np.frombuffer(audio.samples, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return audio

    energy = np.abs(samples)
    above = np.where(energy > energy_threshold)[0]
    if above.size == 0:
        # Entirely below threshold: nothing to trim to, leave as-is and let
        # the too_short check downstream reject it on duration instead of
        # this function fabricating an empty clip.
        return audio

    start, end = int(above[0]), int(above[-1]) + 1
    trimmed = (samples[start:end] * 32768.0).astype(np.int16)
    return PcmAudio(samples=trimmed.tobytes(), sample_rate=audio.sample_rate)


class WeSpeakerVerifier(SpeakerVerifier):
    """Real local:wespeaker-resnet34 verifier. Takes an already-built
    `feature_extractor` (see WeSpeakerProvider below for the
    ProviderRegistry-facing wrapper that builds one from a ModelCache) --
    kept this way so tests can inject a fake extractor without a real
    ONNX session (test_wespeaker.py)."""

    id = _PROVIDER_ID

    def __init__(
        self,
        feature_extractor: WeSpeakerFeatureExtractor,
        thresholds: Thresholds,
        min_speech_s: float = _MIN_SPEECH_S_DEFAULT,
        liveness_mode: str = "off",  # requisito 10: no voice anti-spoofing in v1
        variant: str | None = None,
    ) -> None:
        del variant  # no variants yet for voice, kept for ProviderRegistry's uniform call shape
        self._extractor = feature_extractor
        self._thresholds = thresholds
        self._min_speech_s = min_speech_s
        self._liveness_mode = liveness_mode

    async def verify(self, audio: PcmAudio, enrollment: Enrollment) -> BiometricResult:
        if enrollment.model_id != _MODEL_ID:
            raise ModelMismatch("voice", enrollment.profile, _MODEL_ID, enrollment.model_id)

        trimmed = _trim_silence(audio)
        duration_s = len(trimmed.samples) / 2 / trimmed.sample_rate  # 16-bit mono PCM
        if duration_s < self._min_speech_s:
            return self._result(Decision.INCONCLUSIVE, "too_short")

        embedding = self._extractor.embed(trimmed)
        score = pipeline.cosine_similarity(embedding, enrollment.centroid)
        decision = decide(score, self._thresholds, Liveness.NOT_CHECKED, self._liveness_mode)
        return self._result(decision, "ok")

    def _result(self, decision: Decision, reason: str) -> BiometricResult:
        return BiometricResult(
            decision=decision,
            liveness=Liveness.NOT_CHECKED,
            quality_ok=decision != Decision.INCONCLUSIVE or reason == "ok",
            reason=reason,
            provider_id=_PROVIDER_ID,
            model_id=_MODEL_ID,
        )

    async def close(self) -> None:
        return None


class WeSpeakerProvider(WeSpeakerVerifier):
    """ProviderRegistry-facing wrapper for local:wespeaker-resnet34,
    the voice counterpart of SFaceFaceVerifier's (variant, model_cache,
    liveness_mode) constructor shape (see providers/sface.py). Unlike
    WeSpeakerVerifier's own __init__ (which takes an already-built
    feature_extractor, kept that way for test_wespeaker.py's fake-extractor
    tests), this class resolves the `wespeaker` model_cache entry itself
    and builds a real SherpaWeSpeakerExtractor, lazily on first verify() --
    same lazy-load timing SFaceFaceVerifier._ensure_loaded uses, so
    constructing this class (e.g. via ProviderRegistry.resolve_speaker)
    never requires sherpa-onnx or the model file to already be resolvable,
    only actually verifying does.

    This is the class registered under "local" in the ProviderRegistry a
    real BiometricService is built with (see service.py's own
    voice_provider_ref="local" wiring); WeSpeakerVerifier itself stays
    unregistered, reachable only by tests and by manual_camera_check.py's
    direct construction.
    """

    def __init__(
        self,
        variant: str | None = None,
        model_cache: ModelCache | None = None,
        thresholds: Thresholds | None = None,
        liveness_mode: str = "off",  # requisito 10: no voice anti-spoofing in v1
    ) -> None:
        if model_cache is None:
            raise ValueError("WeSpeakerProvider requires a model_cache (see models.py)")
        if variant is not None:
            raise ValueError(
                f"local:wespeaker-resnet34 has no variants, got 'local:{variant}'"
            )
        self._cache = model_cache
        self._initialized = False
        # Same conservative defaults __main__.py's _cmd_bench and
        # manual_camera_check.py's cmd_verify_voice use when no calibrated
        # Thresholds is available: this constructor path (ProviderRegistry)
        # has no calibrate() result to draw on either, unlike a caller that
        # loads calibrated thresholds from config and passes them in.
        self._pending_thresholds = thresholds or Thresholds(t_high=0.7, t_low=0.5)
        self._pending_liveness_mode = liveness_mode
        # Deliberately NOT calling super().__init__() here: it requires an
        # already-built feature_extractor, which needs sherpa-onnx and the
        # resolved model file -- neither should be required just to
        # *construct* this class (matching SFaceFaceVerifier's own
        # lazy-load timing, see its _ensure_loaded). _ensure_loaded below
        # calls super().__init__() for real, once, on first verify().

    def _ensure_loaded(self) -> None:
        if self._initialized:
            return
        model_path = self._cache.resolve("wespeaker")
        extractor = SherpaWeSpeakerExtractor(model_path)
        super().__init__(
            feature_extractor=extractor,
            thresholds=self._pending_thresholds,
            liveness_mode=self._pending_liveness_mode,
        )
        self._initialized = True

    async def verify(self, audio: PcmAudio, enrollment: Enrollment) -> BiometricResult:
        self._ensure_loaded()
        return await super().verify(audio, enrollment)

    async def close(self) -> None:
        self._initialized = False
        return None
