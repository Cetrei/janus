from __future__ import annotations

import pytest

from janus_presence.errors import PresenceUnavailableError


class TestPresenceIndexUnavailable:
    """SPEC.md Edge Cases: 'hnsw-c (.so) ausente o no carga ->
    PresenceUnavailableError al iniciar PresenceIndex'. Exercises the real
    PresenceIndex.__init__ guard without requiring vendor/hnsw/hnsw.a to be
    built, by forcing the module-level `lib` to look unset the way it does
    when the cffi extension failed to import."""

    def test_raises_presence_unavailable_when_native_extension_missing(self, monkeypatch):
        import janus_presence.index as index_module

        monkeypatch.setattr(index_module, "lib", None)
        monkeypatch.setattr(index_module, "_IMPORT_ERROR", ImportError("fake: no such module"))

        with pytest.raises(PresenceUnavailableError):
            index_module.PresenceIndex()
