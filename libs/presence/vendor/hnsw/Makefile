CC = gcc
CFLAGS = -std=c99 -Wall -Wextra -Wpedantic -Iinclude -g
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
	$(CC) $(CFLAGS) -c $< -o $@

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
	$(CC) $(CFLAGS) $^ -lm -o $@

$(BIN)/testInsertSearch: tests/testInsertSearch.c tests/generateSynthetic.c $(SRC) | $(BIN)
	$(CC) $(CFLAGS) $^ -lm -o $@

$(BIN)/testRemove: tests/testRemove.c tests/generateSynthetic.c $(SRC) | $(BIN)
	$(CC) $(CFLAGS) $^ -lm -o $@

$(BIN)/testBenchmark: tests/testBenchmark.c tests/generateSynthetic.c $(SRC) | $(BIN)
	$(CC) $(CFLAGS) $^ -lm -o $@
