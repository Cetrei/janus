/**
 * @file hnsw.h
 * @brief Public API for the hnsw vendored index (Hierarchical Navigable Small World).
 */

#ifndef HNSW_H
#define HNSW_H

/**
 * @brief Construction and search parameters shared by an entire HnswIndex instance.
 */
typedef struct {
    int dim;
    int maxNeighborsPerLayer;
    int efConstruction;
    int efSearch;
    int maxLayers;
} HnswConfig;

/**
 * @brief A single indexed entity: its vector plus its per-layer adjacency lists.
 */
typedef struct {
    int id;
    float *values;
    int layer;
    int **neighborsByLayer;
    int *neighborCountByLayer;
    int isDeleted;
} HnswNode;

/**
 * @brief Root structure owning every node and the current entry point of the graph.
 */
typedef struct {
    HnswConfig config;
    HnswNode *nodes;
    int nodeCount;
    int nodeCapacity;
    int entryPointId;
    int entryPointLayer;
    int *visitedGeneration;
    int visitedGenerationCounter;
} HnswIndex;

/**
 * @brief Result of a k-nearest-neighbors search.
 */
typedef struct {
    int *ids;
    float *distances;
    int count;
} HnswSearchResult;

/**
 * @brief Status codes returned by every fallible hnsw function.
 */
typedef enum {
    HNSW_OK = 0,
    HNSW_ERROR_OUT_OF_MEMORY,
    HNSW_ERROR_INVALID_DIM,
    HNSW_ERROR_NODE_NOT_FOUND,
    HNSW_ERROR_DUPLICATE_ID
} HnswStatus;

/**
 * @brief Allocate and initialize a new, empty HNSW index.
 * @param config Construction parameters (dimension, neighbor limits, ef values, max layers).
 * @param initialCapacity Initial capacity reserved for the internal nodes array.
 * @return Pointer to the new HnswIndex, or NULL if the initial allocation fails.
 */
HnswIndex *hnswIndexCreate(HnswConfig config, int initialCapacity);

/**
 * @brief Free every node, its vectors and adjacency lists, then the index itself.
 * @param index Index to destroy. No-op if NULL.
 */
void hnswIndexDestroy(HnswIndex *index);

/**
 * @brief Insert a new vector into the index under the given id.
 * @param index Target index.
 * @param id Unique identifier for the new node; must not already exist in the index.
 * @param values Pointer to `config.dim` floats; copied internally, ownership stays with the caller.
 * @return HNSW_OK on success, HNSW_ERROR_DUPLICATE_ID if id exists, HNSW_ERROR_OUT_OF_MEMORY on allocation failure.
 */
HnswStatus hnswIndexInsert(HnswIndex *index, int id, float *values);

/**
 * @brief Remove a node from the index, tombstoning it without compacting the nodes array.
 * @param index Target index.
 * @param id Identifier of the node to remove.
 * @return HNSW_OK on success, HNSW_ERROR_NODE_NOT_FOUND if id does not exist or is already removed.
 */
HnswStatus hnswIndexRemove(HnswIndex *index, int id);

/**
 * @brief Search the index for the approximate k nearest neighbors of a query vector.
 * @param index Index to search.
 * @param query Pointer to `config.dim` floats representing the query vector.
 * @param k Number of neighbors requested.
 * @return HnswSearchResult with up to k ids/distances; count may be less than k. Caller must call hnswSearchResultDestroy on the result.
 */
HnswSearchResult hnswIndexSearch(HnswIndex *index, float *query, int k);

/**
 * @brief Free the ids and distances arrays owned by a search result.
 * @param result Result previously returned by hnswIndexSearch.
 */
void hnswSearchResultDestroy(HnswSearchResult result);

/**
 * @brief Compute the squared Euclidean distance between two vectors.
 * @param vectorA First vector, `dim` floats.
 * @param vectorB Second vector, `dim` floats.
 * @param dim Number of elements in both vectors.
 * @return Sum of squared differences; 0.0f if either pointer is NULL or dim <= 0.
 */
float hnswDistanceSquared(float *vectorA, float *vectorB, int dim);

/**
 * @brief Draw a random layer for a new node using the standard HNSW level-assignment formula.
 * @param maxLayers Maximum number of layers allowed in the index.
 * @param maxNeighborsPerLayer Neighbor limit per layer, used to derive the normalization constant mL.
 * @return Layer index in [0, maxLayers - 1].
 */
int hnswAssignRandomLayer(int maxLayers, int maxNeighborsPerLayer);

/**
 * @brief Draw a uniform random float in the (0, 1] range, avoiding exact zero.
 * @return Random value strictly greater than 0.0f and less than or equal to 1.0f.
 */
float hnswUniformRandom(void);

#endif
