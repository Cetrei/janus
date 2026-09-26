#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "hnsw.h"
#include "generateSynthetic.h"

/**
 * @brief Linear brute-force k-nearest-neighbor scan, used only as the benchmark baseline.
 */
static void bruteForceSearch(float *dataset, int count, int dim, float *query, int k) {
    float *dist = (float *)malloc(sizeof(float) * (size_t)count);
    int i, j;

    for (i = 0; i < count; i++) {
        dist[i] = hnswDistanceSquared(&dataset[i * dim], query, dim);
    }
    for (i = 0; i < k && i < count; i++) {
        int bestIdx = i;
        for (j = i + 1; j < count; j++) {
            if (dist[j] < dist[bestIdx]) bestIdx = j;
        }
        {
            float tmp = dist[i]; dist[i] = dist[bestIdx]; dist[bestIdx] = tmp;
        }
    }
    free(dist);
}

static double elapsedSeconds(clock_t start, clock_t end) {
    return (double)(end - start) / CLOCKS_PER_SEC;
}

static void runBenchmarkForSize(int n) {
    const int dim = 12;
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
    config.maxLayers = 6;

    HnswIndex *index = hnswIndexCreate(config, n);

    clock_t insertStart = clock();
    for (i = 0; i < n; i++) {
        hnswIndexInsert(index, i, &dataset[i * dim]);
    }
    clock_t insertEnd = clock();

    float query[12];
    for (i = 0; i < dim; i++) query[i] = 0.5f;

    const int searchRepeats = 20;
    clock_t hnswSearchStart = clock();
    for (i = 0; i < searchRepeats; i++) {
        HnswSearchResult result = hnswIndexSearch(index, query, k);
        hnswSearchResultDestroy(result);
    }
    clock_t hnswSearchEnd = clock();

    clock_t bruteSearchStart = clock();
    for (i = 0; i < searchRepeats; i++) {
        bruteForceSearch(dataset, n, dim, query, k);
    }
    clock_t bruteSearchEnd = clock();

    printf("N=%-7d insert=%.4fs  hnswSearch(avg)=%.6fs  bruteSearch(avg)=%.6fs\n",
        n,
        elapsedSeconds(insertStart, insertEnd),
        elapsedSeconds(hnswSearchStart, hnswSearchEnd) / searchRepeats,
        elapsedSeconds(bruteSearchStart, bruteSearchEnd) / searchRepeats);

    free(dataset);
    hnswIndexDestroy(index);
}

int main(void) {
    int sizes[4] = {100, 1000, 10000, 100000};
    int i;

    printf("Benchmark: HNSW vs. brute force (k=5, dim=12)\n");
    printf("El punto de cruce real (donde HNSW empieza a ganar) se documenta en README.md\n");
    printf("a partir de esta corrida, no se fuerza como assert de CI.\n\n");

    for (i = 0; i < 4; i++) {
        runBenchmarkForSize(sizes[i]);
    }

    return 0;
}
