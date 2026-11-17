/* Progressive sotto 2400 (docs/sotto-progressive.md): the partial-clip decoder's fill step,
 * and a 16 kHz decoder entry that takes filled frames. Not installed; used by the browser
 * demo (docs/progressive.html through c/wasm).
 * SPDX-License-Identifier: MIT */
#ifndef SOTTO_PROG_H
#define SOTTO_PROG_H
#include "sotto_internal.h"

#define SOTTO_PROG_NFIELDS 7   /* c w e s0 s1 s2 s3 */
#define SOTTO_PROG_C 0x01
#define SOTTO_PROG_W 0x02
#define SOTTO_PROG_E 0x04
#define SOTTO_PROG_S0 0x08     /* s1, s2, s3: 0x10, 0x20, 0x40 */
#define SOTTO_PROG_ALL 0x7F

/* The 2400 layout's field widths, in the order of the known bits. */
const int *sotto_prog_field_bits(void);

/* The prior shape for a voicing code (sim/data/prog_prior.npz). */
void sotto_prog_prior(int code, double c[SOTTO_K - 1]);

/* n frames of 6 bytes, known[f] = the fields of frame f that arrived (SOTTO_PROG_* bits).
 * Writes each frame's filled fields p[f], its row (the bits with the filled voicing and pitch
 * fields, which carry the hiss index and the side-channel bit) and sgood[f] (1 when its voicing,
 * pitch and energy arrived: the side channel trusts only those frames). With every field known,
 * p and rows are exactly what the streamed decoder reads from the bits. */
void sotto_prog_fill2400(const unsigned char *bits, const unsigned char *known, int n, sotto_fparams_t *p,
                         unsigned char *rows, unsigned char *sgood);

/* sotto_decode16 for a frame whose fields are given (p, its row and sgood from
 * sotto_prog_fill2400), as a good frame. A stream decoded this way with every field known
 * gives the same samples as sotto_decode16. End with sotto_dec16_flush as usual. */
struct sotto_dec16;
void sotto_decode16_params(struct sotto_dec16 *d, const sotto_fparams_t *p, const unsigned char row[6], int sgood,
                           short speech[320]);
#endif
