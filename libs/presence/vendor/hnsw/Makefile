CC = gcc
WARNFLAGS = -std=c99 -Wall -Wextra -Wpedantic -Iinclude
# hnsw.a is what libs/presence links against via cffi: optimized, no debug info.
# -O0 vs -O2 measured ~2.2x difference on testBenchmark (N=100000, i7-9750H, gcc 16.2.1);
# release builds must not ship the unoptimized path.
LIBFLAGS = $(WARNFLAGS) -O2
# Tests and the benchmark stay at -O0 -g on purpose: gprof/gdb/valgrind need unmangled,
# non-inlined symbols to stay readable. Never raise these to -O2, or profiling output
# will misattribute time the way it did before this split existed (see AGENT.md).
TESTFLAGS = $(WARNFLAGS) -O0 -g
SRC = src/hnswDistance.c src/hnswRandom.c src/hnswNode.c src/hnswIndex.c src/hnswSearch.c src/hnswMinHeap.c
BIN = bin
OBJ = $(patsubst src/%.c,$(BIN)/%.o,$(SRC))
LIB = hnsw.a

.PHONY: all clean test benchmark

all: $(LIB)

$(LIB): $(OBJ)
	ar rcs $(BIN)/$(LIB) $(OBJ)
	cp $(BIN)/$(LIB) $(LIB)

$(BIN)/%.o: src/%.c | $(BIN)
	$(CC) $(LIBFLAGS) -c $< -o $@

$(BIN):
	mkdir -p $(BIN)

clean:
	rm -rf $(BIN)
	rm -f $(LIB)

test: $(BIN)/testDistanceRandom $(BIN)/testInsertSearch $(BIN)/testRemove
	./$(BIN)/testDistanceRandom
	./$(BIN)/testInsertSearch
	./$(BIN)/testRemove

benchmark: $(BIN)/testBenchmark
	./$(BIN)/testBenchmark

$(BIN)/testDistanceRandom: tests/testDistanceRandom.c $(SRC) | $(BIN)
	$(CC) $(TESTFLAGS) $^ -lm -o $@

$(BIN)/testInsertSearch: tests/testInsertSearch.c tests/generateSynthetic.c $(SRC) | $(BIN)
	$(CC) $(TESTFLAGS) $^ -lm -o $@

$(BIN)/testRemove: tests/testRemove.c tests/generateSynthetic.c $(SRC) | $(BIN)
	$(CC) $(TESTFLAGS) $^ -lm -o $@

$(BIN)/testBenchmark: tests/testBenchmark.c tests/generateSynthetic.c $(SRC) | $(BIN)
	$(CC) $(TESTFLAGS) $^ -lm -o $@
