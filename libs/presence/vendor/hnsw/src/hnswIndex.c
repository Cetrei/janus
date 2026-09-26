#include <stdlib.h>
#include "hnsw.h"
#include "hnswInternal.h"

static HnswStatus hnswGrowCapacity(HnswIndex *index);
static void hnswReplaceFarthestNeighbor(HnswIndex *index, HnswLayerRef ref, int candidateId);
static void hnswConnectCandidate(HnswLayerWalk walk, int newId, int candidateId);
static HnswStatus hnswConnectNodeAtLayer(HnswLayerWalk walk, int newId, int *outClosestId);
static void hnswReelectEntryPoint(HnswIndex *index);

/**
 * @brief Allocate and initialize a new, empty HNSW index.
 * @param config Construction parameters (dimension, neighbor limits, ef values, max layers).
 * @param initialCapacity Initial capacity reserved for the internal nodes array.
 * @return Pointer to the new HnswIndex, or NULL if the initial allocation fails.
 */
HnswIndex *hnswIndexCreate(HnswConfig config, int initialCapacity) {
    HnswIndex *index;

    if (initialCapacity <= 0) initialCapacity = 1;

    index = (HnswIndex *)malloc(sizeof(HnswIndex));
    if (index == NULL) return NULL;

    index->nodes = (HnswNode *)malloc(sizeof(HnswNode) * (size_t)initialCapacity);
    if (index->nodes == NULL) {
        free(index);
        return NULL;
    }

    index->visitedGeneration = (int *)calloc((size_t)initialCapacity, sizeof(int));
    if (index->visitedGeneration == NULL) {
        free(index->nodes);
        free(index);
        return NULL;
    }

    index->config = config;
    index->nodeCount = 0;
    index->nodeCapacity = initialCapacity;
    index->entryPointId = -1;
    index->entryPointLayer = -1;
    index->visitedGenerationCounter = 0;
    return index;
}

/**
 * @brief Free every node, its vectors and adjacency lists, then the index itself.
 * @param index Index to destroy. No-op if NULL.
 */
void hnswIndexDestroy(HnswIndex *index) {
    int nodeIndex;

    if (index == NULL) return;

    for (nodeIndex = 0; nodeIndex < index->nodeCount; nodeIndex++) {
        hnswNodeDestroy(&index->nodes[nodeIndex]);
    }
    free(index->nodes);
    free(index->visitedGeneration);
    free(index);
}

/**
 * @brief Double the internal nodes array capacity.
 * @param index Index whose capacity is grown.
 * @return HNSW_OK on success, HNSW_ERROR_OUT_OF_MEMORY if reallocation fails.
 */
static HnswStatus hnswGrowCapacity(HnswIndex *index) {
    int newCapacity;
    HnswNode *newNodes;
    int *newVisitedGeneration;
    int growIndex;

    newCapacity = index->nodeCapacity * 2;
    newNodes = (HnswNode *)realloc(index->nodes, sizeof(HnswNode) * (size_t)newCapacity);
    if (newNodes == NULL) return HNSW_ERROR_OUT_OF_MEMORY;
    index->nodes = newNodes;

    newVisitedGeneration = (int *)realloc(index->visitedGeneration, sizeof(int) * (size_t)newCapacity);
    if (newVisitedGeneration == NULL) return HNSW_ERROR_OUT_OF_MEMORY;
    index->visitedGeneration = newVisitedGeneration;
    for (growIndex = index->nodeCapacity; growIndex < newCapacity; growIndex++) {
        index->visitedGeneration[growIndex] = 0;
    }

    index->nodeCapacity = newCapacity;
    return HNSW_OK;
}

/**
 * @brief Resolve a node's array position from its id in O(1), since id is defined as the array index.
 * @param index Index to search.
 * @param id Identifier to look up.
 * @return `id` itself if it falls within the currently used range, -1 otherwise.
 */
int hnswFindNodePosition(HnswIndex *index, int id) {
    if (id < 0 || id >= index->nodeCount) return -1;
    return id;
}

/**
 * @brief Walk greedily from a starting node toward the closest live node to query at a given layer.
 * @param walk Index, query vector, layer and starting node id for the walk.
 * @return Id of the closest node found at that layer.
 */
int hnswFindClosestAtLayer(HnswLayerWalk walk) {
    int currentId;
    int improved;

    currentId = walk.startId;
    improved = 1;

    while (improved) {
        int currentPos = hnswFindNodePosition(walk.index, currentId);
        float bestDist = hnswDistanceSquared(walk.index->nodes[currentPos].values, walk.query, walk.index->config.dim);
        int bestId = currentId;
        int neighborIndex;

        improved = 0;
        if (walk.layer > walk.index->nodes[currentPos].layer) continue;

        for (neighborIndex = 0; neighborIndex < walk.index->nodes[currentPos].neighborCountByLayer[walk.layer]; neighborIndex++) {
            int neighborId = walk.index->nodes[currentPos].neighborsByLayer[walk.layer][neighborIndex];
            int neighborPos = hnswFindNodePosition(walk.index, neighborId);
            float dist;

            if (neighborPos == -1 || walk.index->nodes[neighborPos].isDeleted) continue;

            dist = hnswDistanceSquared(walk.index->nodes[neighborPos].values, walk.query, walk.index->config.dim);
            if (dist < bestDist || (dist == bestDist && neighborId < bestId)) {
                bestDist = dist;
                bestId = neighborId;
                improved = 1;
            }
        }
        currentId = bestId;
    }
    return currentId;
}

/**
 * @brief Reconsider a full neighbor list against a new candidate and keep the closest entries.
 *
 * The previous implementation only compared the candidate against the single farthest
 * incumbent neighbor and swapped it in on a win. That is a biased, order-dependent
 * selection: once a node's slots fill up with whatever arrived first, later candidates
 * can only displace the single worst slot, even when several incumbents are farther
 * than the candidate. Over many inserts this starves well-connected long-range edges
 * and fragments the graph into locally dense but poorly linked clusters, which is why
 * greedy search stalled near the entry point instead of reaching distant true neighbors.
 * This version pools the existing neighbors plus the candidate into a bounded set, sorts
 * by distance, and keeps the maxNeighborsPerLayer closest, matching the intent of HNSW's
 * neighbor-selection pruning step.
 *
 * @param index Index owning both nodes, used to compare distances.
 * @param ref Node id and layer whose full neighbor list is being reconsidered.
 * @param candidateId Id of the candidate competing for a slot in that neighbor list.
 */
static void hnswReplaceFarthestNeighbor(HnswIndex *index, HnswLayerRef ref, int candidateId) {
    int pos;
    int *neighborList;
    int neighborCount;
    HnswBoundedSet pool;
    int slotIndex;

    pos = hnswFindNodePosition(index, ref.nodeId);
    neighborList = index->nodes[pos].neighborsByLayer[ref.layer];
    neighborCount = index->nodes[pos].neighborCountByLayer[ref.layer];

    pool = hnswBoundedSetCreate(neighborCount + 1);
    if (pool.ids == NULL || pool.distances == NULL) {
        hnswBoundedSetDestroy(&pool);
        return;
    }

    for (slotIndex = 0; slotIndex < neighborCount; slotIndex++) {
        int slotPos = hnswFindNodePosition(index, neighborList[slotIndex]);
        float slotDist = hnswDistanceSquared(index->nodes[pos].values, index->nodes[slotPos].values, index->config.dim);
        hnswBoundedSetInsertSorted(&pool, neighborList[slotIndex], slotDist);
    }

    {
        int candidatePos = hnswFindNodePosition(index, candidateId);
        float candidateDist = hnswDistanceSquared(index->nodes[pos].values, index->nodes[candidatePos].values, index->config.dim);
        hnswBoundedSetInsertSorted(&pool, candidateId, candidateDist);
    }

    for (slotIndex = 0; slotIndex < neighborCount && slotIndex < pool.count; slotIndex++) {
        neighborList[slotIndex] = pool.ids[slotIndex];
    }

    hnswBoundedSetDestroy(&pool);
}

/**
 * @brief Connect a candidate node to the new node at one layer, pruning both adjacency lists.
 * @param walk Index and target layer shared by the whole connection round.
 * @param newId Id of the newly inserted node.
 */
static void hnswConnectCandidate(HnswLayerWalk walk, int newId, int candidateId) {
    int candidatePos;
    int newPos;
    HnswLayerRef refToCandidate;
    HnswLayerRef refToNew;

    candidatePos = hnswFindNodePosition(walk.index, candidateId);
    newPos = hnswFindNodePosition(walk.index, newId);
    if (candidatePos == newPos) return;

    refToCandidate.nodeId = candidateId;
    refToCandidate.layer = walk.layer;
    refToNew.nodeId = newId;
    refToNew.layer = walk.layer;

    if (hnswNodeAddNeighbor(&walk.index->nodes[newPos], refToCandidate, walk.index->config.maxNeighborsPerLayer) != HNSW_OK) {
        hnswReplaceFarthestNeighbor(walk.index, refToNew, candidateId);
    }

    if (hnswNodeAddNeighbor(&walk.index->nodes[candidatePos], refToNew, walk.index->config.maxNeighborsPerLayer) != HNSW_OK) {
        hnswReplaceFarthestNeighbor(walk.index, refToCandidate, newId);
    }
}

/**
 * @brief Connect a newly inserted node to its M diversity-selected nearest candidates at one layer.
 *
 * Runs the wide efConstruction expansion, then reduces that pool to M neighbors with
 * hnswSelectNeighborsHeuristic before connecting anything. Connecting all efConstruction
 * candidates directly (skipping this reduction) was tried first and made every insertion
 * attempt roughly efConstruction/M times more connections than the graph's degree bound
 * allows, most of which immediately triggered the expensive prune path in
 * hnswReplaceFarthestNeighbor on both sides of each attempted edge. That cost grew with
 * graph density (more existing nodes already at their neighbor cap), which is why
 * insertion time grew faster than linearly with the number of nodes already indexed.
 * Selecting M neighbors up front keeps connection attempts, and therefore prune calls,
 * bounded by the degree bound instead of by efConstruction.
 *
 * Also returns the closest candidate found during the wide expansion, so the caller can
 * hand it off as the entry point for the next lower layer instead of re-deriving it with
 * a single-path greedy walk. Reusing the wide-expansion result matters because greedy-1
 * descent only reliably finds the global optimum in the sparse upper layers of HNSW; at
 * layer 0, where the graph is dense and can be organized into several separate local
 * neighborhoods, greedy-1 can settle into whichever neighborhood its current position
 * already belongs to and never cross into a different one. Handing off the best node
 * found by the ef-wide search keeps each layer's entry point tied to the same broad
 * search that just ran, instead of narrowing back down to a single path between layers.
 *
 * @param walk Index, the new node's vector, target layer and the local search entry id.
 * @param newId Id of the newly inserted node.
 * @param outClosestId Receives the id of the closest candidate found at this layer.
 * @return HNSW_OK on success.
 */
static HnswStatus hnswConnectNodeAtLayer(HnswLayerWalk walk, int newId, int *outClosestId) {
    HnswBoundedSet candidates;
    HnswBoundedSet selected;
    HnswNeighborSelection selection;
    int selectedIndex;
    int ef;

    ef = walk.index->config.efConstruction;
    candidates = hnswExpandLayer(walk, ef);

    if (candidates.count > 0) {
        *outClosestId = candidates.ids[0];
    } else {
        *outClosestId = walk.startId;
    }

    selection.index = walk.index;
    selection.baseId = newId;
    selection.candidates = candidates;
    selection.layer = walk.layer;
    selected = hnswSelectNeighborsHeuristic(selection, walk.index->config.maxNeighborsPerLayer);

    for (selectedIndex = 0; selectedIndex < selected.count; selectedIndex++) {
        hnswConnectCandidate(walk, newId, selected.ids[selectedIndex]);
    }

    hnswBoundedSetDestroy(&selected);
    hnswBoundedSetDestroy(&candidates);
    return HNSW_OK;
}

/**
 * @brief Insert a new vector into the index under the given id.
 * @param index Target index.
 * @param id Unique identifier for the new node; must not already exist in the index.
 * @param values Pointer to `config.dim` floats; copied internally, ownership stays with the caller.
 * @return HNSW_OK on success, HNSW_ERROR_DUPLICATE_ID if id exists, HNSW_ERROR_OUT_OF_MEMORY on allocation failure.
 */
HnswStatus hnswIndexInsert(HnswIndex *index, int id, float *values) {
    int layer;
    int pos;
    HnswStatus status;

    if (index == NULL || values == NULL) return HNSW_ERROR_INVALID_DIM;
    if (id >= 0 && id < index->nodeCount && !index->nodes[id].isDeleted) return HNSW_ERROR_DUPLICATE_ID;
    if (id != index->nodeCount) return HNSW_ERROR_INVALID_DIM;

    if (index->nodeCount >= index->nodeCapacity) {
        status = hnswGrowCapacity(index);
        if (status != HNSW_OK) return status;
    }

    layer = hnswAssignRandomLayer(index->config.maxLayers, index->config.maxNeighborsPerLayer);
    pos = index->nodeCount;

    {
        HnswNodeInitParams initParams;
        initParams.id = id;
        initParams.values = values;
        initParams.dim = index->config.dim;
        initParams.layer = layer;
        initParams.maxNeighborsPerLayer = index->config.maxNeighborsPerLayer;

        status = hnswNodeInit(&index->nodes[pos], initParams);
        if (status != HNSW_OK) return status;
    }

    index->nodeCount++;

    if (index->entryPointId == -1) {
        index->entryPointId = id;
        index->entryPointLayer = layer;
        return HNSW_OK;
    }

    {
        HnswLayerWalk walk;
        int currentLayer;
        int lowerBound;

        walk.index = index;
        walk.query = values;
        walk.startId = index->entryPointId;

        for (currentLayer = index->entryPointLayer; currentLayer > layer; currentLayer--) {
            walk.layer = currentLayer;
            walk.startId = hnswFindClosestAtLayer(walk);
        }

        lowerBound = layer < index->entryPointLayer ? layer : index->entryPointLayer;
        for (currentLayer = lowerBound; currentLayer >= 0; currentLayer--) {
            int closestAtLayer;
            walk.layer = currentLayer;
            hnswConnectNodeAtLayer(walk, id, &closestAtLayer);
            walk.startId = closestAtLayer;
        }
    }

    if (layer > index->entryPointLayer) {
        index->entryPointId = id;
        index->entryPointLayer = layer;
    }

    return HNSW_OK;
}

/**
 * @brief Re-elect the entry point among remaining live nodes, preferring the highest layer.
 * @param index Index whose entry point is stale or missing.
 */
static void hnswReelectEntryPoint(HnswIndex *index) {
    int nodeIndex;
    int bestId = -1;
    int bestLayer = -1;

    for (nodeIndex = 0; nodeIndex < index->nodeCount; nodeIndex++) {
        if (index->nodes[nodeIndex].isDeleted) continue;
        if (index->nodes[nodeIndex].layer > bestLayer) {
            bestLayer = index->nodes[nodeIndex].layer;
            bestId = index->nodes[nodeIndex].id;
        }
    }
    index->entryPointId = bestId;
    index->entryPointLayer = bestLayer;
}

/**
 * @brief Remove a node from the index, tombstoning it without compacting the nodes array.
 * @param index Target index.
 * @param id Identifier of the node to remove.
 * @return HNSW_OK on success, HNSW_ERROR_NODE_NOT_FOUND if id does not exist or is already removed.
 */
HnswStatus hnswIndexRemove(HnswIndex *index, int id) {
    int pos;
    int layerIndex;
    int neighborIndex;

    if (index == NULL) return HNSW_ERROR_NODE_NOT_FOUND;

    pos = hnswFindNodePosition(index, id);
    if (pos == -1 || index->nodes[pos].isDeleted) return HNSW_ERROR_NODE_NOT_FOUND;

    for (layerIndex = 0; layerIndex <= index->nodes[pos].layer; layerIndex++) {
        for (neighborIndex = 0; neighborIndex < index->nodes[pos].neighborCountByLayer[layerIndex]; neighborIndex++) {
            int neighborId = index->nodes[pos].neighborsByLayer[layerIndex][neighborIndex];
            int neighborPos = hnswFindNodePosition(index, neighborId);

            if (neighborPos != -1) {
                HnswLayerRef ref;
                ref.nodeId = id;
                ref.layer = layerIndex;
                hnswNodeRemoveNeighbor(&index->nodes[neighborPos], ref);
            }
        }
    }

    free(index->nodes[pos].values);
    index->nodes[pos].values = NULL;
    index->nodes[pos].isDeleted = 1;

    if (index->entryPointId == id) {
        hnswReelectEntryPoint(index);
    }

    return HNSW_OK;
}
