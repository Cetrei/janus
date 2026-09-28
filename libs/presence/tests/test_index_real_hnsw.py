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

    def test_ids_can_arrive_in_any_order_with_gaps(self):
        # hnsw-c itself only accepts id == nodeCount on insert, but
        # PresenceIndex keeps durable ids apart from node positions, so
        # the startup rebuild can feed it ids in any order and with gaps
        # left by forgotten people. Only a live duplicate is refused.
        from janus_presence.errors import PresenceUnavailableError
        from janus_presence.index import EMBEDDING_DIM, PresenceIndex

        index = PresenceIndex()
        try:
            index.insert(5, [5.0] * EMBEDDING_DIM)
            index.insert(3, [3.0] * EMBEDDING_DIM)
            index.insert(9, [9.0] * EMBEDDING_DIM)

            nearest = index.search([3.1] * EMBEDDING_DIM, k=1)
            assert nearest[0][0] == 3

            with pytest.raises(PresenceUnavailableError):
                index.insert(5, [0.0] * EMBEDDING_DIM)
        finally:
            index.close()

    def test_removed_id_can_be_inserted_again(self):
        from janus_presence.index import EMBEDDING_DIM, PresenceIndex

        index = PresenceIndex()
        try:
            index.insert(2, [1.0] * EMBEDDING_DIM)
            index.remove(2)
            index.insert(2, [8.0] * EMBEDDING_DIM)

            nearest = index.search([8.0] * EMBEDDING_DIM, k=1)
            assert nearest[0][0] == 2
        finally:
            index.close()
