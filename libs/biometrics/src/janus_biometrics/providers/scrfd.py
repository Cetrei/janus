"""Intentionally empty / not used.

SCRFD support was first drafted here as a separate ScrfdFaceVerifier
subclass of SFaceFaceVerifier, but that duplicated the registry wiring for
no benefit: ProviderRegistry already resolves "local:<variant>" refs by
passing `variant` into whatever single class is registered under "local"
(see registry.py's ProviderRef / test_registry.py's
test_variant_is_passed_to_factory), so SFaceFaceVerifier itself now
branches on `variant in ("sface", "scrfd", None)` to pick YuNet or SCRFD
for detection while sharing 100% of the liveness/embedding/decision code.

See providers/sface.py's SFaceFaceVerifier docstring ("Variants" section)
for the real, current documentation of local:scrfd, and
_face_pipeline.detect_faces_scrfd for the SCRFD detection/decoding itself.

This file is kept (rather than deleted) only because this session's
filesystem tooling has no delete operation available; it deliberately
defines nothing importable, so an accidental `from
janus_biometrics.providers.scrfd import ScrfdFaceVerifier` fails loudly
with ImportError instead of silently resolving to a stale, unused class.
Safe to actually delete whenever a future session has a delete tool.
"""

from __future__ import annotations
