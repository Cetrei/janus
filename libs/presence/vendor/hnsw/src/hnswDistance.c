#include <stddef.h>
#include "hnsw.h"

/**
 * @brief Compute the squared Euclidean distance between two vectors.
 * @param vectorA First vector, `dim` floats.
 * @param vectorB Second vector, `dim` floats.
 * @param dim Number of elements in both vectors.
 * @return Sum of squared differences; 0.0f if either pointer is NULL or dim <= 0.
 */
float hnswDistanceSquared(float *vectorA, float *vectorB, int dim) {
    float sum;
    int i;

    if (vectorA == NULL || vectorB == NULL || dim <= 0) return 0.0f;

    sum = 0.0f;
    for (i = 0; i < dim; i++) {
        float diff = vectorA[i] - vectorB[i];
        sum += diff * diff;
    }
    return sum;
}
