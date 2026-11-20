/* sotto 1200 slim encoder: a light analysis and coder for a Cortex-M0 with a few KB of RAM
 * (the Baofeng UV-K6), writing ordinary sotto 1200 superframes (docs/sotto-slim.md).
 * SPDX-License-Identifier: MIT */
#ifndef SOTTO_SLIM_H
#define SOTTO_SLIM_H
#include <stdint.h>

#define SLIM_NC 19                 /* shape values a frame (FX_NC) */
#define SLIM_BYTES 6               /* a superframe (SOTTO_BYTES_PER_FRAME) */

/* one 20 ms frame's fields before quantization of the shape */
typedef struct {
  int16_t code, wi, ei;            /* voicing code, 7-bit pitch index, 5-bit energy code */
  int16_t c[SLIM_NC];              /* shape: DCT coefficients 1..19 of the envelope, dB Q8 */
} slim_frame_t;

typedef struct slim_enc slim_enc_t;

/* the state lives in the caller's memory: slim_enc_bytes() of it, int32 aligned */
unsigned slim_enc_bytes(void);
void slim_enc_init(slim_enc_t *e);
/* 10 ms of 8 kHz speech in; returns the number of superframes written to out (0 or 1) */
int slim_encode10(slim_enc_t *e, const int16_t x[80], unsigned char out[SLIM_BYTES]);
/* after the last block: call until it returns 0 */
int slim_flush(slim_enc_t *e, unsigned char out[SLIM_BYTES]);

/* the two halves on their own (the bench mixes them with the full encoder's):
   slim_analyse10 returns 1 when a 20 ms frame is ready in *f; slim_analyse_flush the same
   after the input's end; slim_coder_* is sotto 1200's coder on 20 ms frames */
int slim_analyse10(slim_enc_t *e, const int16_t x[80], slim_frame_t *f);
int slim_analyse_flush(slim_enc_t *e, slim_frame_t *f);
int slim_coder_push(slim_enc_t *e, const slim_frame_t *f, unsigned char out[SLIM_BYTES]);
int slim_coder_flush(slim_enc_t *e, unsigned char out[SLIM_BYTES]);

/* tuning knobs of the bench build (-DSLIM_TUNE): slim_tune[i], see sotto_fx_slim.c */
#ifdef SLIM_TUNE
extern int slim_tune[32];
#endif
#endif
