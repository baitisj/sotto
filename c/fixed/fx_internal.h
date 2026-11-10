/* Shared between the fixed-point core (sotto_fx_enc.c, sotto_fx_dec.c) and the v3.8 layer
 * (sotto_fx_hiss.c): the integer twin of ../sotto_internal.h. Not installed.
 * SPDX-License-Identifier: MIT */
#ifndef SOTTO_FX_INTERNAL_H
#define SOTTO_FX_INTERNAL_H
#include "../sotto.h"
#include "fx.h"
#include "fx_tables.h"

#define FX_NFB 7                      /* hiss_band.FB: 1250 .. 3800 Hz */
#define FX_SNR_NONE INT32_MIN         /* snr of an unvoiced half (the float's NAN) */

/* the fields of one 20 ms frame as the decoder core takes them (sotto 1200 builds them) */
typedef struct {
  int16_t code, wi, ei;               /* voicing code, 7-bit pitch index, 5-bit energy code */
  int32_t c[FX_NC];                   /* shape: DCT coefficients 1..K-1, dB Q16 */
} fx_fparams_t;

/* one 20 ms frame out of the v3.7 encoder core, with what the v3.8 rules need per 10 ms half */
typedef struct {
  unsigned char bits[SOTTO_BYTES_PER_FRAME];
  int32_t en[2];                      /* mean of the rate-K envelope, dB Q8 (hiss_band._onsets) */
  int32_t tilt[2];                    /* mean rk below 1 kHz - mean rk above 2 kHz, dB Q8 */
  int32_t snr[2];                     /* harmonic SNR below 1 kHz, dB Q8; FX_SNR_NONE when unvoiced */
  int32_t lwo[2];                     /* ln of the tracked Wo in radians, Q16 (pitch jitter) */
  int16_t loud[2];                    /* above the causal loudness reference */
} fx_enc_frame_t;

/* what the v3.8 decoder layer reads back after each core frame */
typedef struct {
  int32_t env[2][FX_NFB];             /* dB Q8 envelope at FB of the two halves just synthesised */
  int16_t cls[2];                     /* their class: 0 unvoiced, 1 voiced, 2 mixed */
#if defined(FX_HISS_FB)
  int32_t bands[1][16];               /* the K6 layer: hiss_band.model_bands of the odd half only */
#elif defined(FX_HISS_LIGHT)
  int32_t bands[2][16];               /* K6 light layer: hiss_band.model_bands of each half at
                                         FLO + (3000, 3500), dB Q8 */
#endif
  unsigned char b2[SOTTO_BYTES_PER_FRAME];   /* the bits the frame just received decodes (concealed) */
  int16_t run;                        /* lost frames in a row, 0 for a good frame */
} fx_dec_info_t;

void sotto_enc_analyse_block(struct sotto_enc *e, const short x8[80]);
/* the encoder core with its FFT scratch (FX_ENC_SCRATCH values, free between calls) at
   scratch, shared with its owner's (the v3.8 layer's STFT), or its own (NULL, as
   sotto_enc_create); sotto_fx_enc_shared_bytes is its state without the scratch */
#define FX_ENC_SCRATCH 1024
struct sotto_enc *sotto_enc_create_scratch(int32_t *scratch);
unsigned sotto_fx_enc_shared_bytes(void);
void sotto_enc_flush_core(struct sotto_enc *e);
int sotto_enc_pop_frame(struct sotto_enc *e, fx_enc_frame_t *f);
/* the same, with the frame's fields before shape quantization as the low-rate coders take
   them (the float core's sotto_enc_frame_t.p: the shape target, the onset-edge pitch); f or p
   may be NULL */
int sotto_enc_pop_frame_p(struct sotto_enc *e, fx_enc_frame_t *f, fx_fparams_t *p);
/* on: the core skips its own 4-stage shape search (frames' shape bits are 0), for a coder
   that quantises the shape itself (sotto 1200) */
void sotto_enc_set_no_shape(struct sotto_enc *e, int on);

/* the encoder core's M-best codebook search (sotto_fx_enc.c), for sotto 1200's coder:
   fx_msvq_paths searches the first nst stages for target c (dB Q16) and returns the number
   of surviving paths, with their indices and reconstructions (dB Q16), in list order;
   fx_shape_err is the squared error of a reconstruction, sum of (c - rec)^2 in dB Q8;
   fx_cb_best is the nearest vector of stage s to residual r (codebook steps Q6, FX_NC values
   and a 0 pad, |r|^2 = rr), the first of equals. hv: scratch for 512 values */
#define FX_MBEST 8
#define FX_MAXST 5
int fx_msvq_paths(const int32_t *c, int nst, int16_t path[FX_MBEST][FX_MAXST], int32_t recon[FX_MBEST][FX_NC],
                  int32_t *hv);
fx_acc fx_shape_err(const int32_t *c, const int32_t *rec);
int fx_cb_best(int s, const int16_t *r, fx_acc rr, int32_t *hv);
void sotto_dec_frame(struct sotto_dec *d, const fx_fparams_t *p, int run, short speech[160]);
const fx_dec_info_t *sotto_dec_info(const struct sotto_dec *d);

/* The K6 hiss layer (sotto_fx_hiss.c, FX_HISS_FB) hooks into the fixed-point sotto 1200 and
   sotto 600 / 400 decoders as ../sotto_hiss.c does into the float ones (../sotto_internal.h):
   the decoder calls the hook after every 20 ms frame the core takes, with the frame's voicing
   code and concealment run and the core's 160 samples out; flushed = 1 for the core's last
   output. sotto 1200's gives the frame's 4-band hiss residual (dB Q8), its side-channel bit and
   whether its superframe arrived (sgood); sotto 600 / 400's the frame's number g, whether its
   superframe arrived or was rebuilt (avail) and whether it was rebuilt (reb): the layer reads
   the superframes' hiss fields itself. */
struct sotto_lr_dec;
typedef void (*fx_lr_hiss_hook_t)(void *ctx, int code, const int32_t *res, int side, int sgood, int run,
                                  const short *out, int flushed);
void sotto_lr_dec_set_hook(struct sotto_lr_dec *d, fx_lr_hiss_hook_t hook, void *ctx);
const struct sotto_dec *sotto_lr_dec_core(const struct sotto_lr_dec *d);
struct sotto_vlr_dec;
typedef void (*fx_vlr_hiss_hook_t)(void *ctx, int g, int code, int run, int avail, int reb, const short *out,
                                   int flushed);
void sotto_vlr_dec_set_hook(struct sotto_vlr_dec *d, fx_vlr_hiss_hook_t hook, void *ctx);
const struct sotto_dec *sotto_vlr_dec_core(const struct sotto_vlr_dec *d);
/* sotto 1200 hiss's encoder (sotto_fx_hiss.c, VARIANT=v3.8): sotto 1200's coder without its
   core (sotto_fx_lr_enc.c), fed the 20 ms frames after v3.8's voicing rules, and the frames
   sotto 1200's decoder rebuilds from superframe sf and the next (NULL: sf is the last), as
   ../sotto_internal.h's float ones */
struct sotto_lr_enc;
struct sotto_lr_enc *sotto_lr_enc_create_frames(void);
void sotto_lr_enc_push(struct sotto_lr_enc *e, const fx_fparams_t *p);
void sotto_lr_enc_end(struct sotto_lr_enc *e);
int sotto_lr_enc_pop(struct sotto_lr_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]);
unsigned sotto_fx_lr_coder_bytes(void);
void fx_lr_frames(const unsigned char *sf, const unsigned char *next, fx_fparams_t *a, fx_fparams_t *b);
#endif
