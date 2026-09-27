"""Integration tests against the real compiled hnsw-c binary (SPEC.md
Testing Requirements, Integration Tests + Memory/Bridge Tests).

Requires `vendor/hnsw/hnsw.a` to be built and the package installed so
`janus_presence._hnsw_cffi` exists:

    cd vendor/hnsw && make && cd ../..
    uv sync

No longer skipped: hnsw.a is built and janus_presence._hnsw_cffi is part
of the normal editable install (build_hnsw.py runs as a build hook), so
these run as regular tests. If the native extension is ever missing in an
environment, PresenceIndex() itself raises PresenceUnavailableError with a
clear message (see test_index.py) rather than these silently skipping.
"""

from __future__ import annotations

import pytest


class TestPresenceIndexAgainstRealHnsw:
    def test_insert_and_search_returns_nearest(self):
        from janus_presence.index import EMBEDDING_DIM, PresenceIndex

        index = PresenceIndex()
        try:
            # hnsw-c requires ids to be assigned sequentially starting at 0
            # (hnswIndexInsert rejects `id != nodeCount`, surfaced here as
            # HNSW_ERROR_INVALID_DIM despite the name): id=0 is the node
            # closest to the query, id=1 is far.
            index.insert(0, [0.0] * EMBEDDING_DIM)
            index.insert(1, [10.0] * EMBEDDING_DIM)
            results = index.search([0.1] * EMBEDDING_DIM, k=1)
            assert results[0][0] == 0
        finally:
            index.close()

    def test_remove_then_search_excludes_id(self):
        from janus_presence.index import EMBEDDING_DIM, PresenceIndex

        index = PresenceIndex()
        try:
            index.insert(0, [0.0] * EMBEDDING_DIM)
            index.remove(0)
            results = index.search([0.0] * EMBEDDING_DIM, k=1)
            assert all(hnsw_id != 0 for hnsw_id, _ in results)
        finally:
            index.close()

    def test_dimension_mismatch_raises_value_error(self):
        from janus_presence.index import PresenceIndex

        index = PresenceIndex()
        try:
            with pytest.raises(ValueError):
                index.insert(0, [0.0] * 4)
        finally:
            index.close()

    def test_ids_must_be_sequential_from_zero(self):
        # Documents a real constraint of the vendored hnsw-c
        # (hnswIndexInsert), not a janus_presence choice: the first id in
        # an empty index must be 0, not an arbitrary integer. A caller
        # that skips ahead gets PresenceUnavailableError (index.py maps
        # every non-OK HnswStatus to it), not a crash.
        from janus_presence.errors import PresenceUnavailableError
        from janus_presence.index import EMBEDDING_DIM, PresenceIndex

        index = PresenceIndex()
        try:
            with pytest.raises(PresenceUnavailableError):
                index.insert(1, [0.0] * EMBEDDING_DIM)
        finally:
            index.close()
