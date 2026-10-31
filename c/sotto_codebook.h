/* Shape codebook: sotto_cb_stages stages of 2^sotto_cb_bits[s] vectors of 19 DCT
 * coefficients (float32, row-major), 34 bits in all. Generated from an .npz codebook
 * (default sim/data/shape_msvq_34.npz) by tools/export_codebook_c.py. */
#ifndef SOTTO_CODEBOOK_H
#define SOTTO_CODEBOOK_H
#define SOTTO_CB_MAX_STAGES 5
extern const int sotto_cb_stages;
extern const int sotto_cb_bits[];
extern const float *const sotto_cb[];
#endif
