#include <stdio.h>
#include <stdlib.h>
#include "hnsw.h"
#include "generateSynthetic.h"

static int check(int condition, const char *name) {
    printf("%s: %s\n", name, condition ? "OK" : "FAIL");
    return condition ? 0 : 1;
}

/**
 * @brief Compute the k nearest ids to a query via linear brute-force scan, for test comparison only.
 */
static void bruteForceKNearest(float *dataset, int count, int dim, float *query, int k, int *outIds) {
    float *dist = (float *)malloc(sizeof(float) * (size_t)count);
    int i, j;

    for (i = 0; i < count; i++) {
        dist[i] = hnswDistanceSquared(&dataset[i * dim], query, dim);
    }
    for (i = 0; i < k; i++) {
        int bestIdx = i;
        for (j = i + 1; j < count; j++) {
            if (dist[j] < dist[bestIdx]) bestIdx = j;
        }
        {
            float tmpD = dist[i]; dist[i] = dist[bestIdx]; dist[bestIdx] = tmpD;
            int tmpId = outIds[i]; outIds[i] = outIds[bestIdx]; outIds[bestIdx] = tmpId;
        }
    }
    free(dist);
}

static int idInArray(int id, int *arr, int count) {
    int i;
    for (i = 0; i < count; i++) if (arr[i] == id) return 1;
    return 0;
}

int main(void) {
    int failures = 0;
    const int dim = 12;
    const int n = 200;
    const int k = 5;
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
    failures += check(index != NULL, "indexCreateNotNull");

    for (i = 0; i < n; i++) {
        HnswStatus status = hnswIndexInsert(index, i, &dataset[i * dim]);
        if (status != HNSW_OK) { failures += check(0, "insertAllOk"); break; }
    }
    if (i == n) failures += check(1, "insertAllOk");

    failures += check(hnswIndexInsert(index, 0, &dataset[0]) == HNSW_ERROR_DUPLICATE_ID, "insertDuplicateRejected");

    float query[12];
    for (i = 0; i < dim; i++) query[i] = 0.5f;

    HnswSearchResult result = hnswIndexSearch(index, query, k);
    failures += check(result.count == k, "searchReturnsK");

    int *bruteIds = (int *)malloc(sizeof(int) * (size_t)n);
    for (i = 0; i < n; i++) bruteIds[i] = i;
    bruteForceKNearest(dataset, n, dim, query, k, bruteIds);

    int overlap = 0;
    for (i = 0; i < result.count; i++) {
        if (idInArray(result.ids[i], bruteIds, k)) overlap++;
    }
    failures += check(overlap >= (k * 4) / 5, "searchMatchesBruteForceMostly");

    hnswSearchResultDestroy(result);

    HnswIndex *emptyIndex = hnswIndexCreate(config, 4);
    HnswSearchResult emptyResult = hnswIndexSearch(emptyIndex, query, k);
    failures += check(emptyResult.count == 0 && emptyResult.ids == NULL, "searchOnEmptyIndex");
    hnswIndexDestroy(emptyIndex);

    HnswIndex *singleIndex = hnswIndexCreate(config, 1);
    hnswIndexInsert(singleIndex, 0, &dataset[0]);
    HnswSearchResult singleResult = hnswIndexSearch(singleIndex, query, k);
    failures += check(singleResult.count == 1, "searchOnSingleNodeIndex");
    hnswSearchResultDestroy(singleResult);
    hnswIndexDestroy(singleIndex);

    HnswIndex *failIndex = hnswIndexCreate(config, 0);
    failures += check(failIndex != NULL, "createHandlesZeroCapacity");
    hnswIndexDestroy(failIndex);

    free(bruteIds);
    free(dataset);
    hnswIndexDestroy(index);

    if (failures == 0) { printf("All tests passed.\n"); }
    else { printf("%d test(s) failed.\n", failures); }
    return failures;
}
