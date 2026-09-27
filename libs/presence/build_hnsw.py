"""cffi build script (API mode), invoked by pyproject.toml's build backend.

hnsw-c only produces a static library (hnsw.a) via `make`, not a shared
object, so cffi's ABI/dlopen mode does not apply here: this compiles a real
C extension module (janus_presence._hnsw_cffi) that links hnsw.a directly,
per the vendor README ("ready for libs/presence to link against via
cffi"). Run `make` in vendor/hnsw/ before building this package; that step
is not repeated here, so a missing hnsw.a fails loudly at build time
instead of silently rebuilding it in a way that could produce a
non-release (-O0) binary by accident (see vendor/hnsw/README.md's
warning about hnsw.a always needing -O2).
"""

from __future__ import annotations

from pathlib import Path

from cffi import FFI

_VENDOR_ROOT = Path(__file__).parent / "vendor" / "hnsw"
_HEADER_PATH = _VENDOR_ROOT / "include" / "hnsw.h"
_LIB_PATH = _VENDOR_ROOT / "hnsw.a"

if not _LIB_PATH.exists():
    raise FileNotFoundError(
        f"{_LIB_PATH} not found. Build it first: `cd {_VENDOR_ROOT} && make`. "
        "This must be the -O2 release build (plain `make`, not `make test`/`make benchmark`)."
    )

ffibuilder = FFI()

# Trimmed, cffi-parseable restatement of include/hnsw.h's declarations
# (cffi's cdef parser does not accept Doxygen comments or the full
# preprocessor, so this must be kept in sync by hand with the real header
# whenever hnsw.h's public API changes).
ffibuilder.cdef(
    """
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
    float hnswDistanceSquared(float *vectorA, float *vectorB, int dim);
    """
)

ffibuilder.set_source(
    "janus_presence._hnsw_cffi",
    """
    #include "hnsw.h"
    """,
    include_dirs=[str(_VENDOR_ROOT / "include")],
    extra_objects=[str(_LIB_PATH)],
)

if __name__ == "__main__":
    # tmpdir keeps generated .c/.o files out of src/; target= places the
    # built extension directly under src/janus_presence so it is
    # importable as janus_presence._hnsw_cffi without a separate install
    # step.
    ffibuilder.compile(
        tmpdir=str(Path(__file__).parent / "build"),
        target=str(Path(__file__).parent / "src" / "janus_presence" / "_hnsw_cffi.*"),
        verbose=True,
    )
