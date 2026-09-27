#include <stdlib.h>
#include "hnsw.h"
#include "hnswInternal.h"

static void hnswMinHeapSwap(HnswMinHeap *heap, int indexA, int indexB);
static void hnswMinHeapSiftUp(HnswMinHeap *heap, int index);
static void hnswMinHeapSiftDown(HnswMinHeap *heap, int index);

/**
 * @brief Allocate an empty min-heap with initial room for `initialCapacity` entries.
 * @param initialCapacity Starting capacity; the heap grows automatically past this.
 * @return The new heap. Its arrays are NULL if allocation fails; count stays 0.
 */
HnswMinHeap hnswMinHeapCreate(int initialCapacity) {
    HnswMinHeap heap;

    if (initialCapacity <= 0) initialCapacity = 1;

    heap.count = 0;
    heap.capacity = initialCapacity;
    heap.ids = (int *)malloc(sizeof(int) * (size_t)initialCapacity);
    heap.distances = (float *)malloc(sizeof(float) * (size_t)initialCapacity);
    return heap;
}

/**
 * @brief Free a min-heap's backing arrays.
 * @param heap Heap to release.
 */
void hnswMinHeapDestroy(HnswMinHeap *heap) {
    free(heap->ids);
    free(heap->distances);
}

/**
 * @brief Swap two slots in a min-heap's backing arrays.
 * @param heap Heap being modified.
 * @param indexA First slot.
 * @param indexB Second slot.
 */
static void hnswMinHeapSwap(HnswMinHeap *heap, int indexA, int indexB) {
    int tmpId = heap->ids[indexA];
    float tmpDist = heap->distances[indexA];

    heap->ids[indexA] = heap->ids[indexB];
    heap->distances[indexA] = heap->distances[indexB];
    heap->ids[indexB] = tmpId;
    heap->distances[indexB] = tmpDist;
}

/**
 * @brief Restore the min-heap property by moving a newly inserted entry upward.
 * @param heap Heap being modified.
 * @param index Slot of the entry to sift up.
 */
static void hnswMinHeapSiftUp(HnswMinHeap *heap, int index) {
    while (index > 0) {
        int parent = (index - 1) / 2;

        if (heap->distances[parent] <= heap->distances[index]) break;
        hnswMinHeapSwap(heap, parent, index);
        index = parent;
    }
}

/**
 * @brief Restore the min-heap property by moving an entry downward.
 * @param heap Heap being modified.
 * @param index Slot of the entry to sift down.
 */
static void hnswMinHeapSiftDown(HnswMinHeap *heap, int index) {
    while (1) {
        int left = index * 2 + 1;
        int right = index * 2 + 2;
        int smallest = index;

        if (left < heap->count && heap->distances[left] < heap->distances[smallest]) smallest = left;
        if (right < heap->count && heap->distances[right] < heap->distances[smallest]) smallest = right;
        if (smallest == index) break;

        hnswMinHeapSwap(heap, index, smallest);
        index = smallest;
    }
}

/**
 * @brief Push an id/distance pair onto the heap, growing its backing arrays if needed.
 * @param heap Heap to insert into.
 * @param id Identifier to insert.
 * @param dist Distance associated with the identifier.
 * @return HNSW_OK on success, HNSW_ERROR_OUT_OF_MEMORY if growing the backing arrays fails.
 */
HnswStatus hnswMinHeapPush(HnswMinHeap *heap, int id, float dist) {
    if (heap->count >= heap->capacity) {
        int newCapacity = heap->capacity * 2;
        int *newIds = (int *)realloc(heap->ids, sizeof(int) * (size_t)newCapacity);
        float *newDistances;

        if (newIds == NULL) return HNSW_ERROR_OUT_OF_MEMORY;
        heap->ids = newIds;

        newDistances = (float *)realloc(heap->distances, sizeof(float) * (size_t)newCapacity);
        if (newDistances == NULL) return HNSW_ERROR_OUT_OF_MEMORY;
        heap->distances = newDistances;

        heap->capacity = newCapacity;
    }

    heap->ids[heap->count] = id;
    heap->distances[heap->count] = dist;
    hnswMinHeapSiftUp(heap, heap->count);
    heap->count++;
    return HNSW_OK;
}

/**
 * @brief Remove and return the minimum-distance entry from the heap.
 * @param heap Heap to pop from; must have count > 0.
 * @param outId Receives the removed entry's id.
 * @param outDist Receives the removed entry's distance.
 */
void hnswMinHeapPopMin(HnswMinHeap *heap, int *outId, float *outDist) {
    *outId = heap->ids[0];
    *outDist = heap->distances[0];

    heap->count--;
    heap->ids[0] = heap->ids[heap->count];
    heap->distances[0] = heap->distances[heap->count];
    hnswMinHeapSiftDown(heap, 0);
}
