/* Shape codebook: SOTTO_CB_STAGES stages of 2^sotto_cb_bits[s] vectors of 19 DCT
 * coefficients (float32, row-major). Generated from sim/data/shape_msvq_34.npz by
 * tools/export_codebook_c.py. */
#ifndef SOTTO_CODEBOOK_H
#define SOTTO_CODEBOOK_H
#define SOTTO_CB_STAGES 3
extern const int sotto_cb_bits[SOTTO_CB_STAGES];
extern const float *const sotto_cb[SOTTO_CB_STAGES];
#endif
