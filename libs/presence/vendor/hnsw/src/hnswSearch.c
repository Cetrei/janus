#include <stdlib.h>
#include "hnsw.h"
#include "hnswInternal.h"

/**
 * @brief Allocate an empty bounded set with room for `capacity` entries.
 * @param capacity Maximum number of entries the set will ever hold.
 * @return The new set. Its arrays are NULL if allocation fails; count stays 0.
 */
HnswBoundedSet hnswBoundedSetCreate(int capacity) {
    HnswBoundedSet set;

    set.count = 0;
    set.capacity = capacity;
    set.ids = (int *)malloc(sizeof(int) * (size_t)capacity);
    set.distances = (float *)malloc(sizeof(float) * (size_t)capacity);
    return set;
}

/**
 * @brief Free a bounded set's backing arrays.
 * @param set Set to release.
 */
void hnswBoundedSetDestroy(HnswBoundedSet *set) {
    free(set->ids);
    free(set->distances);
}

/**
 * @brief Remove and return the closest entry from a sorted bounded set, shifting the rest left.
 * @param set Set to pop from; must have count > 0.
 * @param outId Receives the removed entry's id.
 * @param outDist Receives the removed entry's distance.
 */
void hnswBoundedSetPopClosest(HnswBoundedSet *set, int *outId, float *outDist) {
    int shiftIndex;

    *outId = set->ids[0];
    *outDist = set->distances[0];

    for (shiftIndex = 0; shiftIndex < set->count - 1; shiftIndex++) {
        set->ids[shiftIndex] = set->ids[shiftIndex + 1];
        set->distances[shiftIndex] = set->distances[shiftIndex + 1];
    }
    set->count--;
}

/**
 * @brief Insert an id/distance pair into a bounded set, keeping it sorted and capped at capacity.
 * @param set Set to insert into.
 * @param id Identifier to insert.
 * @param dist Distance associated with the identifier.
 */
void hnswBoundedSetInsertSorted(HnswBoundedSet *set, int id, float dist) {
    int insertAt;

    if (set->count >= set->capacity && dist >= set->distances[set->count - 1]) return;

    insertAt = set->count < set->capacity ? set->count : set->capacity - 1;
    while (insertAt > 0 && (set->distances[insertAt - 1] > dist ||
           (set->distances[insertAt - 1] == dist && set->ids[insertAt - 1] > id))) {
        if (insertAt < set->capacity) {
            set->ids[insertAt] = set->ids[insertAt - 1];
            set->distances[insertAt] = set->distances[insertAt - 1];
        }
        insertAt--;
    }
    set->ids[insertAt] = id;
    set->distances[insertAt] = dist;
    if (set->count < set->capacity) set->count++;
}

/**
 * @brief Expand a layer from an entry point via frontier traversal, keeping the ef closest live nodes.
 *
 * Marks visited nodes using the index's visitedGeneration buffer stamped with a fresh
 * generation number, instead of allocating and zeroing a nodeCount-sized buffer on every
 * call. Since this function runs roughly once per layer per insertion (so on the order of
 * N times total), a fresh calloc(nodeCount) per call made construction O(N) work times
 * O(N) calls, i.e. quadratic, regardless of how efficient the rest of the traversal was.
 * Bumping a counter and stamping only the nodes actually visited keeps each call's own
 * visited-tracking cost proportional to what it visits, not to the whole index.
 *
 * Stops the frontier walk with `break`, not `continue`, once a popped candidate is
 * already worse than the current worst kept result and `results` is full: no candidate
 * still in the min-heap can be closer than the one just popped, so nothing left in the
 * heap can improve `results` either, and draining the rest of the heap was pure waste.
 * Likewise, a neighbor is only pushed onto the frontier when it could still improve
 * `results` (the same condition already used to decide whether to keep it); pushing
 * every unvisited neighbor unconditionally let the frontier balloon with nodes that
 * were never going to be popped productively, since each expansion adds up to
 * maxNeighborsPerLayer new entries regardless of whether they are promising. Before
 * this fix, `hnswExpandLayer` was doing roughly 10x more heap pushes than `ef` should
 * require per call (measured while profiling construction at N=50000), because neither
 * limit was in place; this restores both halves of the pruning from SEARCH-LAYER
 * (Malkov & Yashunin, Algorithm 2) that a wide, unfiltered frontier had been skipping.
 *
 * @param walk Index, query vector, target layer and starting node id.
 * @param ef Maximum number of result candidates to keep.
 * @return A bounded set with up to `ef` closest ids/distances found, sorted ascending by distance.
 */
HnswBoundedSet hnswExpandLayer(HnswLayerWalk walk, int ef) {
    HnswBoundedSet results;
    HnswMinHeap frontier;
    int generation;
    int startPos;
    float startDist;

    walk.index->visitedGenerationCounter++;
    generation = walk.index->visitedGenerationCounter;

    results = hnswBoundedSetCreate(ef);
    frontier = hnswMinHeapCreate(ef > 0 ? ef : 1);

    startPos = hnswFindNodePosition(walk.index, walk.startId);
    startDist = hnswDistanceSquared(walk.index->nodes[startPos].values, walk.query, walk.index->config.dim);

    walk.index->visitedGeneration[walk.startId] = generation;
    hnswBoundedSetInsertSorted(&results, walk.startId, startDist);
    hnswMinHeapPush(&frontier, walk.startId, startDist);

    while (frontier.count > 0) {
        int currentId;
        int currentPos;
        int neighborIndex;
        int frontierLayer;
        float currentDistPopped;

        hnswMinHeapPopMin(&frontier, &currentId, &currentDistPopped);

        if (results.count >= ef && currentDistPopped > results.distances[results.count - 1]) break;

        currentPos = hnswFindNodePosition(walk.index, currentId);
        frontierLayer = walk.layer <= walk.index->nodes[currentPos].layer ? walk.layer : walk.index->nodes[currentPos].layer;

        for (neighborIndex = 0; neighborIndex < walk.index->nodes[currentPos].neighborCountByLayer[frontierLayer]; neighborIndex++) {
            int neighborId = walk.index->nodes[currentPos].neighborsByLayer[frontierLayer][neighborIndex];
            int neighborPos = hnswFindNodePosition(walk.index, neighborId);
            float neighborDist;

            if (neighborPos == -1 || walk.index->nodes[neighborPos].isDeleted) continue;
            if (walk.index->visitedGeneration[neighborId] == generation) continue;

            neighborDist = hnswDistanceSquared(walk.index->nodes[neighborPos].values, walk.query, walk.index->config.dim);
            walk.index->visitedGeneration[neighborId] = generation;

            if (results.count < ef || neighborDist < results.distances[results.count - 1]) {
                hnswMinHeapPush(&frontier, neighborId, neighborDist);
                hnswBoundedSetInsertSorted(&results, neighborId, neighborDist);
            }
        }
    }

    hnswMinHeapDestroy(&frontier);
    return results;
}

/**
 * @brief Reduce a candidate pool to at most m neighbors using HNSW's diversity heuristic.
 *
 * Implements SELECT-NEIGHBORS-HEURISTIC from Malkov & Yashunin (Algorithm 4), with
 * extendCandidates fixed to false (its benefit is limited to extremely clustered data
 * and it costs an extra neighborhood expansion per candidate) and keepPrunedConnections
 * fixed to true (so a base element still gets m neighbors even when the diversity
 * condition discards most of the pool, which matters for small or sparse graphs).
 *
 * Candidates are considered nearest-to-base first; a candidate is kept only if it is
 * closer to the base element than every neighbor already kept. This favors connections
 * in diverse directions over a cluster of near-duplicate candidates all pointing the
 * same way, which is what keeps the graph navigable instead of only locally dense.
 *
 * @param selection Index, base element id, candidate pool (any order) and target layer.
 * @param m Maximum number of neighbors to return.
 * @return Up to m selected neighbor ids/distances, sorted ascending by distance to base.
 */
HnswBoundedSet hnswSelectNeighborsHeuristic(HnswNeighborSelection selection, int m) {
    HnswBoundedSet selected;
    HnswBoundedSet discarded;
    HnswBoundedSet *pool;
    int candidateIndex;

    selected = hnswBoundedSetCreate(m);
    discarded = hnswBoundedSetCreate(selection.candidates.count > 0 ? selection.candidates.count : 1);
    pool = &selection.candidates;

    for (candidateIndex = 0; candidateIndex < pool->count && selected.count < m; candidateIndex++) {
        int candidateId = pool->ids[candidateIndex];
        float candidateDistToBase = pool->distances[candidateIndex];
        int candidatePos;
        int selectedIndex;
        int isDiverse;

        if (candidateId == selection.baseId) continue;

        candidatePos = hnswFindNodePosition(selection.index, candidateId);
        isDiverse = 1;

        for (selectedIndex = 0; selectedIndex < selected.count; selectedIndex++) {
            int keptPos = hnswFindNodePosition(selection.index, selected.ids[selectedIndex]);
            float distCandidateToKept = hnswDistanceSquared(
                selection.index->nodes[candidatePos].values,
                selection.index->nodes[keptPos].values,
                selection.index->config.dim);

            if (distCandidateToKept <= candidateDistToBase) {
                isDiverse = 0;
                break;
            }
        }

        if (isDiverse) {
            hnswBoundedSetInsertSorted(&selected, candidateId, candidateDistToBase);
        } else {
            hnswBoundedSetInsertSorted(&discarded, candidateId, candidateDistToBase);
        }
    }

    for (candidateIndex = 0; candidateIndex < discarded.count && selected.count < m; candidateIndex++) {
        hnswBoundedSetInsertSorted(&selected, discarded.ids[candidateIndex], discarded.distances[candidateIndex]);
    }

    hnswBoundedSetDestroy(&discarded);
    return selected;
}

/**
 * @brief Search the index for the approximate k nearest neighbors of a query vector.
 * @param index Index to search.
 * @param query Pointer to `config.dim` floats representing the query vector.
 * @param k Number of neighbors requested.
 * @return HnswSearchResult with up to k ids/distances; count may be less than k. Caller must call hnswSearchResultDestroy on the result.
 */
HnswSearchResult hnswIndexSearch(HnswIndex *index, float *query, int k) {
    HnswSearchResult result;
    HnswLayerWalk walk;
    HnswBoundedSet candidates;
    int currentLayer;
    int liveCount;
    int nodeIndex;
    int ef;

    result.ids = NULL;
    result.distances = NULL;
    result.count = 0;

    if (index == NULL || query == NULL || k <= 0 || index->entryPointId == -1) return result;

    liveCount = 0;
    for (nodeIndex = 0; nodeIndex < index->nodeCount; nodeIndex++) {
        if (!index->nodes[nodeIndex].isDeleted) liveCount++;
    }
    if (liveCount == 0) return result;

    walk.index = index;
    walk.query = query;
    walk.startId = index->entryPointId;

    for (currentLayer = index->entryPointLayer; currentLayer > 0; currentLayer--) {
        walk.layer = currentLayer;
        walk.startId = hnswFindClosestAtLayer(walk);
    }

    ef = index->config.efSearch > k ? index->config.efSearch : k;
    if (ef > liveCount) ef = liveCount;

    walk.layer = 0;
    candidates = hnswExpandLayer(walk, ef);

    result.count = k < candidates.count ? k : candidates.count;
    result.ids = (int *)malloc(sizeof(int) * (size_t)result.count);
    result.distances = (float *)malloc(sizeof(float) * (size_t)result.count);
    if (result.ids == NULL || result.distances == NULL) {
        free(result.ids);
        free(result.distances);
        hnswBoundedSetDestroy(&candidates);
        result.ids = NULL;
        result.distances = NULL;
        result.count = 0;
        return result;
    }

    for (nodeIndex = 0; nodeIndex < result.count; nodeIndex++) {
        result.ids[nodeIndex] = candidates.ids[nodeIndex];
        result.distances[nodeIndex] = candidates.distances[nodeIndex];
    }

    hnswBoundedSetDestroy(&candidates);
    return result;
}

/**
 * @brief Free the ids and distances arrays owned by a search result.
 * @param result Result previously returned by hnswIndexSearch.
 */
void hnswSearchResultDestroy(HnswSearchResult result) {
    free(result.ids);
    free(result.distances);
}
