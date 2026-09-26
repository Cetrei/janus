from __future__ import annotations

from pathlib import Path

import numpy as np
from cffi import FFI

from janus_presence.errors import PresenceUnavailableError

_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "hnsw"
_LIBRARY_PATH = _VENDOR_DIR / "hnsw.a"

_CDEF = """
typedef struct {
    int dim;
    int maxNeighborsPerLayer;
    int efConstruction;
    int efSearch;
    int maxLayers;
} HnswConfig;

typedef struct {
    int *ids;
    float *distances;
    int count;
} HnswSearchResult;

typedef enum {
    HNSW_OK = 0,
    HNSW_ERROR_OUT_OF_MEMORY,
    HNSW_ERROR_INVALID_DIM,
    HNSW_ERROR_NODE_NOT_FOUND,
    HNSW_ERROR_DUPLICATE_ID
} HnswStatus;

typedef struct HnswIndex HnswIndex;

HnswIndex *hnswIndexCreate(HnswConfig config, int initialCapacity);
void hnswIndexDestroy(HnswIndex *index);
HnswStatus hnswIndexInsert(HnswIndex *index, int id, float *values);
HnswStatus hnswIndexRemove(HnswIndex *index, int id);
HnswSearchResult hnswIndexSearch(HnswIndex *index, float *query, int k);
void hnswSearchResultDestroy(HnswSearchResult result);
"""

_EMBEDDING_DIM = 128


class PresenceIndex:
    def __init__(
        self,
        dim: int = _EMBEDDING_DIM,
        max_neighbors_per_layer: int = 16,
        ef_construction: int = 200,
        ef_search: int = 64,
        max_layers: int = 16,
        initial_capacity: int = 64,
    ) -> None:
        self._dim = dim
        self._ffi, self._lib = self._load_library()
        config = self._ffi.new(
            "HnswConfig *",
            {
                "dim": dim,
                "maxNeighborsPerLayer": max_neighbors_per_layer,
                "efConstruction": ef_construction,
                "efSearch": ef_search,
                "maxLayers": max_layers,
            },
        )[0]
        index_ptr = self._lib.hnswIndexCreate(config, initial_capacity)
        if index_ptr == self._ffi.NULL:
            raise PresenceUnavailableError("hnswIndexCreate returned NULL")
        self._index = index_ptr

    def _load_library(self):
        if not _LIBRARY_PATH.exists():
            raise PresenceUnavailableError(
                f"vendored hnsw library not found at {_LIBRARY_PATH}; "
                "run `make` in vendor/hnsw before using PresenceIndex"
            )
        ffi = FFI()
        ffi.cdef(_CDEF)
        try:
            lib = ffi.dlopen(str(_LIBRARY_PATH))
        except OSError as exc:
            raise PresenceUnavailableError(f"failed to load {_LIBRARY_PATH}: {exc}") from exc
        return ffi, lib

    def insert(self, hnsw_id: int, embedding: np.ndarray) -> int:
        buffer = self._as_contiguous_buffer(embedding)
        status = self._lib.hnswIndexInsert(
            self._index, hnsw_id, self._ffi.cast("float *", buffer.ctypes.data)
        )
        if status != self._lib.HNSW_OK:
            raise PresenceUnavailableError(f"hnswIndexInsert failed: status={status}")
        return hnsw_id

    def search(self, embedding: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
        buffer = self._as_contiguous_buffer(embedding)
        result = self._lib.hnswIndexSearch(
            self._index, self._ffi.cast("float *", buffer.ctypes.data), k
        )
        try:
            return [(result.ids[i], result.distances[i]) for i in range(result.count)]
        finally:
            self._lib.hnswSearchResultDestroy(result)

    def remove(self, hnsw_id: int) -> None:
        status = self._lib.hnswIndexRemove(self._index, hnsw_id)
        if status != self._lib.HNSW_OK:
            raise PresenceUnavailableError(f"hnswIndexRemove failed: status={status}")

    def close(self) -> None:
        if self._index is not None:
            self._lib.hnswIndexDestroy(self._index)
            self._index = None

    def _as_contiguous_buffer(self, embedding: np.ndarray) -> np.ndarray:
        if embedding.shape != (self._dim,):
            raise ValueError(f"embedding must have shape ({self._dim},), got {embedding.shape}")
        return np.ascontiguousarray(embedding, dtype=np.float32)
