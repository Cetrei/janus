/**
 * @file hnswInternal.h
 * @brief Internal cross-file declarations, not part of the public hnsw.h API.
 */

#ifndef HNSW_INTERNAL_H
#define HNSW_INTERNAL_H

#include "hnsw.h"

/**
 * @brief Parameters needed to allocate and initialize a single node.
 */
typedef struct {
    int id;
    float *values;
    int dim;
    int layer;
    int maxNeighborsPerLayer;
} HnswNodeInitParams;

/**
 * @brief A node/layer pair, used wherever a neighbor edge must be added, pruned or removed.
 */
typedef struct {
    int nodeId;
    int layer;
} HnswLayerRef;

/**
 * @brief A walk request: which index/layer to search, from which node, toward which query.
 */
typedef struct {
    HnswIndex *index;
    float *query;
    int layer;
    int startId;
} HnswLayerWalk;

/**
 * @brief Bounded, sorted-by-distance working set used during layer expansion (candidates or results).
 */
typedef struct {
    int *ids;
    float *distances;
    int count;
    int capacity;
} HnswBoundedSet;

/**
 * @brief Binary min-heap of (id, distance) pairs, ordered by ascending distance. Grows as needed.
 *
 * Used for the frontier/candidate set during layer expansion, where the number of
 * elements pushed is not bounded by a small constant like `ef` and a plain sorted
 * array with shifted inserts would degrade toward O(n) per push.
 */
typedef struct {
    int *ids;
    float *distances;
    int count;
    int capacity;
} HnswMinHeap;

HnswStatus hnswNodeInit(HnswNode *node, HnswNodeInitParams params);
void hnswNodeFreeLayersUpTo(HnswNode *node, int upToLayer);
void hnswNodeDestroy(HnswNode *node);
HnswStatus hnswNodeAddNeighbor(HnswNode *node, HnswLayerRef ref, int maxNeighborsPerLayer);
void hnswNodeRemoveNeighbor(HnswNode *node, HnswLayerRef ref);

int hnswFindNodePosition(HnswIndex *index, int id);
int hnswFindClosestAtLayer(HnswLayerWalk walk);

HnswBoundedSet hnswBoundedSetCreate(int capacity);
void hnswBoundedSetDestroy(HnswBoundedSet *set);
void hnswBoundedSetInsertSorted(HnswBoundedSet *set, int id, float dist);
HnswBoundedSet hnswExpandLayer(HnswLayerWalk walk, int ef);

/**
 * @brief The base element and candidate pool that SELECT-NEIGHBORS-HEURISTIC reduces to M neighbors.
 */
typedef struct {
    HnswIndex *index;
    int baseId;
    HnswBoundedSet candidates;
    int layer;
} HnswNeighborSelection;

HnswBoundedSet hnswSelectNeighborsHeuristic(HnswNeighborSelection selection, int m);

HnswMinHeap hnswMinHeapCreate(int initialCapacity);
void hnswMinHeapDestroy(HnswMinHeap *heap);
HnswStatus hnswMinHeapPush(HnswMinHeap *heap, int id, float dist);
void hnswMinHeapPopMin(HnswMinHeap *heap, int *outId, float *outDist);

#endif
