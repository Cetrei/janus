#include <stdio.h>
#include <stdlib.h>
#include "hnsw.h"
#include "generateSynthetic.h"

static int check(int condition, const char *name) {
    printf("%s: %s\n", name, condition ? "OK" : "FAIL");
    return condition ? 0 : 1;
}

static int idInResult(int id, HnswSearchResult *result) {
    int i;
    for (i = 0; i < result->count; i++) if (result->ids[i] == id) return 1;
    return 0;
}

int main(void) {
    int failures = 0;
    const int dim = 12;
    const int n = 100;
    float *dataset = (float *)malloc(sizeof(float) * (size_t)(n * dim));
    int i;

    GenerateSyntheticParams genParams;
    genParams.buffer = dataset;
    genParams.count = n;
    genParams.dim = dim;
    generateSyntheticDataset(genParams);

    HnswConfig config;
    config.dim = dim;
    config.maxNeighborsPerLayer = 16;
    config.efConstruction = 32;
    config.efSearch = 32;
    config.maxLayers = 5;

    HnswIndex *index = hnswIndexCreate(config, n);
    for (i = 0; i < n; i++) hnswIndexInsert(index, i, &dataset[i * dim]);

    failures += check(hnswIndexRemove(index, 5) == HNSW_OK, "removeExistingOk");
    failures += check(hnswIndexRemove(index, 5) == HNSW_ERROR_NODE_NOT_FOUND, "removeAlreadyRemoved");
    failures += check(hnswIndexRemove(index, 9999) == HNSW_ERROR_NODE_NOT_FOUND, "removeNonexistent");

    float query[12];
    for (i = 0; i < dim; i++) query[i] = 0.5f;

    HnswSearchResult result = hnswIndexSearch(index, query, n);
    failures += check(!idInResult(5, &result), "removedNodeAbsentFromSearch");
    hnswSearchResultDestroy(result);

    int previousEntryPoint = index->entryPointId;
    hnswIndexRemove(index, previousEntryPoint);
    HnswSearchResult afterEntryRemoval = hnswIndexSearch(index, query, 5);
    failures += check(afterEntryRemoval.count > 0, "searchWorksAfterEntryPointRemoval");
    failures += check(!idInResult(previousEntryPoint, &afterEntryRemoval), "oldEntryPointAbsentFromSearch");
    hnswSearchResultDestroy(afterEntryRemoval);

    HnswIndex *tinyIndex = hnswIndexCreate(config, 1);
    hnswIndexInsert(tinyIndex, 0, &dataset[0]);
    hnswIndexRemove(tinyIndex, 0);
    failures += check(tinyIndex->entryPointId == -1, "removingLastNodeResetsEntryPoint");
    HnswSearchResult emptyAfterRemove = hnswIndexSearch(tinyIndex, query, 5);
    failures += check(emptyAfterRemove.count == 0, "searchOnFullyTombstonedIndex");
    hnswSearchResultDestroy(emptyAfterRemove);
    hnswIndexDestroy(tinyIndex);

    free(dataset);
    hnswIndexDestroy(index);

    if (failures == 0) { printf("All tests passed.\n"); }
    else { printf("%d test(s) failed.\n", failures); }
    return failures;
}
