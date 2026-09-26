#include <stdlib.h>
#include "hnsw.h"
#include "generateSynthetic.h"

/**
 * @brief Fill a preallocated array of vectors with random floats in [0, 1].
 * @param params Target buffer, vector count and dimension to generate.
 */
void generateSyntheticDataset(GenerateSyntheticParams params) {
    int vectorIndex;
    int component;

    for (vectorIndex = 0; vectorIndex < params.count; vectorIndex++) {
        for (component = 0; component < params.dim; component++) {
            params.buffer[vectorIndex * params.dim + component] = hnswUniformRandom();
        }
    }
}
