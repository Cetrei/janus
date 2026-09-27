from __future__ import annotations

from janus_presence.errors import PresenceUnavailableError

try:
    from janus_presence._hnsw_cffi import ffi, lib
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via PresenceIndex.__init__
    ffi = None
    lib = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

EMBEDDING_DIM = 128  # matches the SFace embedding janus_biometrics exposes

_DEFAULT_MAX_NEIGHBORS_PER_LAYER = 16
_DEFAULT_EF_CONSTRUCTION = 200
_DEFAULT_EF_SEARCH = 64
_DEFAULT_MAX_LAYERS = 16
_DEFAULT_INITIAL_CAPACITY = 64

_STATUS_NAMES = {
    1: "HNSW_ERROR_OUT_OF_MEMORY",
    2: "HNSW_ERROR_INVALID_DIM",
    3: "HNSW_ERROR_NODE_NOT_FOUND",
    4: "HNSW_ERROR_DUPLICATE_ID",
}


class PresenceIndex:
    """Wraps the vendored hnsw-c library (requisito 4). `dim=128` to match
    the SFace embeddings janus_biometrics produces. The HNSW id space is a
    presence-internal integer, mapped 1:1 to person_id by PresenceStore
    (requisito 6); this class only ever deals in those integers, never in
    person_id strings.

    hnsw-c has no save/load extension yet (SPEC.md Open Questions), so this
    index only ever lives in memory: PresenceService is responsible for
    rebuilding it at startup from PresenceStore.load_all_samples().
    """

    def __init__(
        self,
        dim: int = EMBEDDING_DIM,
        max_neighbors_per_layer: int = _DEFAULT_MAX_NEIGHBORS_PER_LAYER,
        ef_construction: int = _DEFAULT_EF_CONSTRUCTION,
        ef_search: int = _DEFAULT_EF_SEARCH,
        max_layers: int = _DEFAULT_MAX_LAYERS,
        initial_capacity: int = _DEFAULT_INITIAL_CAPACITY,
    ) -> None:
        if lib is None:
            raise PresenceUnavailableError(
                "hnsw-c",
                f"native extension failed to import ({_IMPORT_ERROR}). "
                "Build it first: run `make` in vendor/hnsw/, then build "
                "janus_presence (build_hnsw.py) so the cffi module exists.",
            )
        self._dim = dim
        config = ffi.new(
            "HnswConfig *",
            {
                "dim": dim,
                "maxNeighborsPerLayer": max_neighbors_per_layer,
                "efConstruction": ef_construction,
                "efSearch": ef_search,
                "maxLayers": max_layers,
            },
        )
        index = lib.hnswIndexCreate(config[0], initial_capacity)
        if index == ffi.NULL:
            raise PresenceUnavailableError(
                "hnsw-c", "hnswIndexCreate returned NULL (out of memory)"
            )
        self._index = index

    def insert(self, hnsw_id: int, embedding: list[float]) -> None:
        self._check_dim(embedding)
        values = ffi.new("float[]", embedding)
        status = lib.hnswIndexInsert(self._index, hnsw_id, values)
        self._raise_on_error(status, f"insert(id={hnsw_id})")

    def remove(self, hnsw_id: int) -> None:
        status = lib.hnswIndexRemove(self._index, hnsw_id)
        self._raise_on_error(status, f"remove(id={hnsw_id})")

    def search(self, embedding: list[float], k: int = 5) -> list[tuple[int, float]]:
        self._check_dim(embedding)
        query = ffi.new("float[]", embedding)
        result = lib.hnswIndexSearch(self._index, query, k)
        try:
            return [(result.ids[i], result.distances[i]) for i in range(result.count)]
        finally:
            lib.hnswSearchResultDestroy(result)

    def close(self) -> None:
        if getattr(self, "_index", None) is not None:
            lib.hnswIndexDestroy(self._index)
            self._index = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        self.close()

    def _check_dim(self, embedding: list[float]) -> None:
        if len(embedding) != self._dim:
            raise ValueError(f"Expected a {self._dim}-dim embedding, got {len(embedding)}")

    def _raise_on_error(self, status: int, operation: str) -> None:
        if status == 0:  # HNSW_OK
            return
        name = _STATUS_NAMES.get(status, f"unknown status {status}")
        raise PresenceUnavailableError("hnsw-c", f"{operation} failed: {name}")
