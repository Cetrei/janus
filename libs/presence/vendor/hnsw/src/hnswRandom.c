#include <stdlib.h>
#include <math.h>
#include "hnsw.h"

/**
 * @brief Draw a uniform random float in the (0, 1] range, avoiding exact zero.
 * @return Random value strictly greater than 0.0f and less than or equal to 1.0f.
 */
float hnswUniformRandom(void) {
    float value;

    value = (float)rand() / ((float)RAND_MAX + 1.0f);
    if (value <= 0.0f) value = 1.0f / ((float)RAND_MAX + 1.0f);
    return value;
}

/**
 * @brief Draw a random layer for a new node using the standard HNSW level-assignment formula.
 * @param maxLayers Maximum number of layers allowed in the index.
 * @param maxNeighborsPerLayer Neighbor limit per layer, used to derive the normalization constant mL.
 * @return Layer index in [0, maxLayers - 1].
 */
int hnswAssignRandomLayer(int maxLayers, int maxNeighborsPerLayer) {
    float mL;
    int layer;

    if (maxLayers <= 0 || maxNeighborsPerLayer <= 1) return 0;

    mL = 1.0f / logf((float)maxNeighborsPerLayer);
    layer = (int)floorf(-logf(hnswUniformRandom()) * mL);

    if (layer >= maxLayers) layer = maxLayers - 1;
    if (layer < 0) layer = 0;
    return layer;
}
