#ifndef GENERATE_SYNTHETIC_H
#define GENERATE_SYNTHETIC_H

/**
 * @brief Parameters for filling a flat buffer with synthetic vectors.
 */
typedef struct {
    float *buffer;
    int count;
    int dim;
} GenerateSyntheticParams;

void generateSyntheticDataset(GenerateSyntheticParams params);

#endif
