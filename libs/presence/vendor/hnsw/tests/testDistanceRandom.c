#include <stdio.h>
#include <math.h>
#include "hnsw.h"

static int check(int condition, const char *name) {
    printf("%s: %s\n", name, condition ? "OK" : "FAIL");
    return condition ? 0 : 1;
}

int main(void) {
    int failures = 0;
    float a[3] = {0.0f, 0.0f, 0.0f};
    float b[3] = {1.0f, 2.0f, 2.0f};
    float dist = hnswDistanceSquared(a, b, 3);
    failures += check(fabsf(dist - 9.0f) < 0.0001f, "distanceSquaredBasic");

    float same[3] = {3.0f, 4.0f, 5.0f};
    failures += check(hnswDistanceSquared(same, same, 3) == 0.0f, "distanceSquaredZero");

    failures += check(hnswDistanceSquared(NULL, b, 3) == 0.0f, "distanceSquaredNullGuard");

    int i;
    int inRange = 1;
    for (i = 0; i < 10000; i++) {
        float r = hnswUniformRandom();
        if (r <= 0.0f || r > 1.0f) inRange = 0;
    }
    failures += check(inRange, "uniformRandomRange");

    int layersInRange = 1;
    for (i = 0; i < 10000; i++) {
        int layer = hnswAssignRandomLayer(5, 16);
        if (layer < 0 || layer >= 5) layersInRange = 0;
    }
    failures += check(layersInRange, "assignRandomLayerRange");

    failures += check(hnswAssignRandomLayer(0, 16) == 0, "assignRandomLayerGuardMaxLayers");
    failures += check(hnswAssignRandomLayer(5, 1) == 0, "assignRandomLayerGuardNeighbors");

    if (failures == 0) { printf("All tests passed.\n");}
    else { printf("%d test(s) failed.\n", failures);}
    return failures;
}
