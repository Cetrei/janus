"""Default ProviderRegistry wiring for a real BiometricService.

Registers the built-in providers by name so a caller does not have to know
which factory belongs to which provider ref:

* "null"  -> NullFaceVerifier / NullSpeakerVerifier (signal disabled)
* "local" -> SFaceFaceVerifier (face) / WeSpeakerProvider (voice), both
             bound to the given ModelCache.

BiometricService resolves providers with `registry.resolve_face(ref)` and
no extra kwargs, so the ModelCache (and voice thresholds) are bound here
by closure rather than passed at resolve time.

The "local" factories import their provider module lazily, inside the
factory, on purpose: providers/sface.py needs opencv and
providers/speaker_wespeaker.py pulls in the same face pipeline, and
neither extra (`face`/`face-gui`, `voice`) is a hard dependency of this
package. Importing this module therefore never requires them; only
*resolving* "local" does, and a missing extra surfaces as ImportError
(or BiometricsError for a missing sherpa-onnx) at that point, which
BiometricService turns into INCONCLUSIVE/model_unavailable (fail closed)
instead of crashing the caller.
"""

from __future__ import annotations

from janus_biometrics.base import FaceVerifier, SpeakerVerifier
from janus_biometrics.models import ModelCache
from janus_biometrics.policy import Thresholds
from janus_biometrics.providers.null import NullFaceVerifier, NullSpeakerVerifier
from janus_biometrics.registry import ProviderRegistry

# Same conservative defaults __main__.py's bench and manual_camera_check.py
# use when no calibrate() result exists yet (calibration_recommended).
DEFAULT_VOICE_THRESHOLDS = Thresholds(t_high=0.7, t_low=0.5)


def build_default_registry(
    model_cache: ModelCache,
    voice_thresholds: Thresholds | None = None,
    face_liveness_mode: str = "required",
) -> ProviderRegistry:
    """Returns a ProviderRegistry with the null and local providers wired
    to `model_cache`. Remote providers stay disabled (requisito 4): this
    registry is built with allow_remote=False, so a dotted-path provider
    ref is rejected until the caller builds its own registry with the
    acknowledgement flags set."""
    thresholds = voice_thresholds or DEFAULT_VOICE_THRESHOLDS
    registry = ProviderRegistry()

    registry.register_face_factory("null", NullFaceVerifier)
    registry.register_speaker_factory("null", NullSpeakerVerifier)

    def make_local_face(variant: str | None = None) -> FaceVerifier:
        from janus_biometrics.providers.sface import SFaceFaceVerifier

        return SFaceFaceVerifier(
            variant=variant, model_cache=model_cache, liveness_mode=face_liveness_mode
        )

    def make_local_speaker(variant: str | None = None) -> SpeakerVerifier:
        from janus_biometrics.providers.speaker_wespeaker import WeSpeakerProvider

        return WeSpeakerProvider(
            variant=variant, model_cache=model_cache, thresholds=thresholds
        )

    registry.register_face_factory("local", make_local_face)
    registry.register_speaker_factory("local", make_local_speaker)
    return registry
