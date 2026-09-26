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

`hnsw.a` is compiled with `-O2` (see `LIBFLAGS` in the Makefile); `make test` and `make benchmark` compile with `-O0 -g` (`TESTFLAGS`) so gprof/gdb/valgrind output stays readable. This split matters: measured on an i7-9750H with gcc 16.2.1, `-O0` vs `-O2` was a ~2.2x difference on `testBenchmark` at N=100000. `hnsw.a` must never regress back to `-O0`, since that is the code path `libs/presence` actually runs in production. Because of this, `make benchmark` numbers are debug-build numbers, not representative of production latency; re-run with a `-O2` build (see AGENT.md's 2026-09-25 entry) if you need real numbers.

It requires `gcc` or `clang` with C99 support. No external dependencies beyond `libc` (`stdlib.h`, `math.h`, `string.h`, `stdio.h` only in tests).

## Licencia

MIT, read [LICENSE]("./LICENSE").
