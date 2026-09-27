#include <stdlib.h>
#include <string.h>
#include "hnsw.h"
#include "hnswInternal.h"

/**
 * @brief Allocate and initialize a node's vector, adjacency arrays and counters.
 * @param node Node to initialize; its fields are overwritten.
 * @param params Identifier, source vector, dimension, assigned layer and per-layer neighbor capacity.
 * @return HNSW_OK on success, HNSW_ERROR_OUT_OF_MEMORY if any allocation fails.
 */
HnswStatus hnswNodeInit(HnswNode *node, HnswNodeInitParams params) {
    int layerIndex;

    if (node == NULL || params.values == NULL || params.dim <= 0) return HNSW_ERROR_INVALID_DIM;

    node->values = (float *)malloc(sizeof(float) * (size_t)params.dim);
    if (node->values == NULL) return HNSW_ERROR_OUT_OF_MEMORY;
    memcpy(node->values, params.values, sizeof(float) * (size_t)params.dim);

    node->neighborsByLayer = (int **)malloc(sizeof(int *) * (size_t)(params.layer + 1));
    if (node->neighborsByLayer == NULL) {
        free(node->values);
        return HNSW_ERROR_OUT_OF_MEMORY;
    }

    node->neighborCountByLayer = (int *)malloc(sizeof(int) * (size_t)(params.layer + 1));
    if (node->neighborCountByLayer == NULL) {
        free(node->values);
        free(node->neighborsByLayer);
        return HNSW_ERROR_OUT_OF_MEMORY;
    }

    for (layerIndex = 0; layerIndex <= params.layer; layerIndex++) {
        node->neighborsByLayer[layerIndex] = (int *)malloc(sizeof(int) * (size_t)params.maxNeighborsPerLayer);
        if (node->neighborsByLayer[layerIndex] == NULL) {
            hnswNodeFreeLayersUpTo(node, layerIndex);
            free(node->neighborsByLayer);
            free(node->neighborCountByLayer);
            free(node->values);
            return HNSW_ERROR_OUT_OF_MEMORY;
        }
        node->neighborCountByLayer[layerIndex] = 0;
    }

    node->id = params.id;
    node->layer = params.layer;
    node->isDeleted = 0;
    return HNSW_OK;
}

/**
 * @brief Free every per-layer neighbor array up to (but not including) a given layer.
 * @param node Node whose partially-allocated layers should be released.
 * @param upToLayer Number of already-allocated layers to free.
 */
void hnswNodeFreeLayersUpTo(HnswNode *node, int upToLayer) {
    int layerIndex;

    if (node == NULL || node->neighborsByLayer == NULL) return;

    for (layerIndex = 0; layerIndex < upToLayer; layerIndex++) {
        free(node->neighborsByLayer[layerIndex]);
    }
}

/**
 * @brief Free a node's vector and every per-layer neighbor array it owns.
 * @param node Node to release. No-op if NULL.
 */
void hnswNodeDestroy(HnswNode *node) {
    int layerIndex;

    if (node == NULL) return;

    free(node->values);
    if (node->neighborsByLayer != NULL) {
        for (layerIndex = 0; layerIndex <= node->layer; layerIndex++) {
            free(node->neighborsByLayer[layerIndex]);
        }
        free(node->neighborsByLayer);
    }
    free(node->neighborCountByLayer);
}

/**
 * @brief Append a neighbor id to a node's adjacency list at a given layer.
 * @param node Node receiving the new neighbor.
 * @param ref Target layer and the neighbor id to add.
 * @param maxNeighborsPerLayer Capacity of the layer's neighbor array.
 * @return HNSW_OK on success, HNSW_ERROR_INVALID_DIM if the layer is out of range or full.
 */
HnswStatus hnswNodeAddNeighbor(HnswNode *node, HnswLayerRef ref, int maxNeighborsPerLayer) {
    if (node == NULL || ref.layer < 0 || ref.layer > node->layer) return HNSW_ERROR_INVALID_DIM;
    if (node->neighborCountByLayer[ref.layer] >= maxNeighborsPerLayer) return HNSW_ERROR_INVALID_DIM;

    node->neighborsByLayer[ref.layer][node->neighborCountByLayer[ref.layer]] = ref.nodeId;
    node->neighborCountByLayer[ref.layer]++;
    return HNSW_OK;
}

/**
 * @brief Remove a neighbor id from a node's adjacency list at a given layer, if present.
 * @param node Node whose neighbor list is modified.
 * @param ref Target layer and the neighbor id to remove.
 */
void hnswNodeRemoveNeighbor(HnswNode *node, HnswLayerRef ref) {
    int position;
    int *neighborList;
    int neighborCount;

    if (node == NULL || ref.layer < 0 || ref.layer > node->layer) return;

    neighborList = node->neighborsByLayer[ref.layer];
    neighborCount = node->neighborCountByLayer[ref.layer];

    for (position = 0; position < neighborCount; position++) {
        if (neighborList[position] == ref.nodeId) {
            neighborList[position] = neighborList[neighborCount - 1];
            node->neighborCountByLayer[ref.layer] = neighborCount - 1;
            return;
        }
    }
}
