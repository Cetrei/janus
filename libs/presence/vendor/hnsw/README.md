# HNSW Index (Hierarchical Navigable Small World) en C puro.
**libs/presence/vendor/hnsw**

Academic work (Universidad Nacional de Costa Rica) that serves as a vector index for `libs/presence/` inside (Janus project)[https://github.com/Cetrei/janus] as source code without git submodule.

## Build

```
make            # compile src/ into bin/ and produce hnsw.a at the repo root
make test       # compile tests into bin/ and run them
make benchmark  # compile and run tests/testBenchmark.c
make clean
```

Object files and test binaries are built under `bin/`. `make` also produces `hnsw.a`, a static library bundling every object file, at the top level next to this README, ready for `libs/presence` to link against via `cffi`.

It requires `gcc` or `clang` with C99 support. No external dependencies beyond `libc` (`stdlib.h`, `math.h`, `string.h`, `stdio.h` only in tests).

## Licencia

MIT, read [LICENSE]("./LICENSE").
