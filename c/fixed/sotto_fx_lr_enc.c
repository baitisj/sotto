/* sotto 1200 encoder in fixed point (integer only), and the stubs of the encoders the
 * fixed-point build doesn't have.
 *
 * sotto 1200: the same coder as the float one in ../sotto_lr.c (sim/sotto_lr.py Sotto1200), on
 * the fixed-point v3.7 encoder core (sotto_fx_enc.c), which hands over each 20 ms frame's
 * fields with its shape target (sotto_enc_pop_frame_p) and skips its own 4-stage shape search.
 * A's shape is the M-best path over the first LR_NA stages (the core's search, fx_msvq_paths),
 * chosen jointly with the B frames on both sides; B's shape is halfway between this A and the
 * next plus 1.5 x one stage-LR_BST codeword; B's pitch and energy are steps from the
 * interpolated indices. Shape errors are sums of squares in dB Q8 (fx_shape_err), the frame
 * weights 1 and 0.1 of the float are 10 and 1. Where float compares near-equal distances the
 * two can choose differently; tools/check_fx.py --lr counts the superframes that differ.
 *
 * There is no fixed-point sotto 600 / 400 encoder (sotto_vlr_enc_create returns NULL; use the
 * float build, ../sotto_vlr.c), nor a fixed-point sotto 600 / 400 hiss (16 kHz) encoder or
 * decoder.
 * SPDX-License-Identifier: MIT */
#define SOTTO_BUILD
#include <stdlib.h>
#include <string.h>
#include "../sotto.h"
#include "../sotto_vlr.h"
#include "../sotto_lr_tables.h"
#include "fx.h"
#include "fx_internal.h"
#include "fx_tables.h"

#define NC FX_NC
#define MBEST FX_MBEST
#define LR_Q 8                     /* 20 ms frames held (ring): A(n), B(n), A(n+1), B(n+1), A(n+2) */
#define LR_OUTQ 4

/* the fields of one superframe, in transmission order */
typedef struct {
  int16_t ca, wa, ea, sa[LR_NA], cb, dw, de, sb;
} lr_fields_t;

static void put_bits(unsigned char *out, int *pos, int v, int nb) {
  int i;
  for (i = nb - 1; i >= 0; i--, (*pos)++)
    if ((v >> i) & 1) out[*pos >> 3] |= 0x80 >> (*pos & 7);
}

static void pack(const lr_fields_t *f, unsigned char *out) {
  int pos = 0, i;
  memset(out, 0, SOTTO_BYTES_PER_FRAME);
  put_bits(out, &pos, f->ca, 2);
  put_bits(out, &pos, f->wa, 7);
  put_bits(out, &pos, f->ea, 5);
  for (i = 0; i < LR_NA; i++) put_bits(out, &pos, f->sa[i], fx_cb_bits[i]);
  put_bits(out, &pos, f->cb, 2);
  put_bits(out, &pos, f->dw, LR_WB_BITS);
  put_bits(out, &pos, f->de, LR_EB_BITS);
  put_bits(out, &pos, f->sb, fx_cb_bits[LR_BST]);
}

/* ------------------------------------------------------------------ the coder */
typedef struct {
  int np;                          /* paths of an A frame's M-best search, best first */
  int16_t path[MBEST][FX_MAXST];
  int32_t rec[MBEST][NC];          /* their reconstructions, dB Q16 */
  int32_t t;                       /* the frame they belong to (-1: none) */
} lr_paths_t;

typedef struct {
  fx_fparams_t p;
  int16_t si[LR_NA];               /* A's shape path (first pass, then joint) */
  int32_t rec[NC];                 /* its reconstruction, dB Q16 */
} lr_aframe_t;

typedef struct {                   /* sotto 1200's coder, fed 20 ms frames */
  fx_fparams_t fr[LR_Q];           /* frames not yet coded (ring) */
  int32_t nin, ncoded;             /* frames received, frames coded (always even) */
  int16_t flushed, have_prev;
  int16_t first;                   /* prevA holds A(0) after its joint search with A(1) (first_ahead) */
  lr_aframe_t prevA;               /* A(n-1), final, for the joint search of A(n) */
  lr_paths_t pc[2];                /* the A frames' searches, by (t / 2) % 2: each is needed twice */
  unsigned char out[LR_OUTQ][SOTTO_BYTES_PER_FRAME];
  int16_t out_head, out_n;
} lr_coder_t;

#define FR(c, t) (&(c)->fr[(t) % LR_Q])

static void coder_init(lr_coder_t *c) {
  memset(c, 0, sizeof *c);
  c->pc[0].t = c->pc[1].t = -1;
}

/* the M-best paths of A frame t (target p), best first (stable, as Sotto1200._a_search with
   all_paths=True); kept, as the frame's first pass and its joint search both need them */
static const lr_paths_t *a_paths(lr_coder_t *c, int32_t t, const fx_fparams_t *p) {
  lr_paths_t *q = &c->pc[(t >> 1) & 1];
  if (q->t != t) {
    int16_t path[MBEST][FX_MAXST];
    int32_t rec[MBEST][NC], hv[512];
    fx_acc d[MBEST];
    int o[MBEST], i, n = fx_msvq_paths(p->c, LR_NA, path, rec, hv);
    for (i = 0; i < n; i++) {                                /* insertion sort, stable */
      int j = i;
      d[i] = fx_shape_err(p->c, rec[i]);
      while (j > 0 && d[o[j - 1]] > d[i]) o[j] = o[j - 1], j--;
      o[j] = i;
    }
    for (i = 0; i < n; i++) {
      memcpy(q->path[i], path[o[i]], sizeof q->path[0]);
      memcpy(q->rec[i], rec[o[i]], sizeof q->rec[0]);
    }
    q->np = n;
    q->t = t;
  }
  return q;
}

/* B's shape error over base (an + ap) / 2 with codeword sb of stage LR_BST (sb < 0: none),
   dB Q8 squared; the sums in Q17 so the base needs no rounding */
static fx_acc b_err(const int32_t *target, const int32_t *an, const int32_t *ap, int sb) {
  int16_t buf[FX_CBW];
  const int16_t *y = sb >= 0 ? FX_CB_VEC(LR_BST, sb, buf) : buf;
  fx_acc d = 0;
  int k;
  for (k = 0; k < NC; k++) {
    int32_t r = 2 * target[k] - an[k] - ap[k];
    if (sb >= 0) r -= 3 * (int32_t)FX_CB_VAL(y, k) * fx_cb_step[LR_BST];
    r = fx_rshr32(r, 9);
    d += (fx_acc)r * r;
  }
  FX_ACC_CHECK(d);
  return d;
}

/* the best stage-LR_BST codeword for B over base (an + ap) / 2, and its error (b_best) */
static fx_acc b_best(const int32_t *target, const int32_t *an, const int32_t *ap, int16_t *sb) {
  int16_t r[NC + 1];
  int32_t hv[512];
  /* residual in steps of LR_BG x the stage's step, Q6: (2 t - an - ap) / 2 x istep / 1.5 */
  int32_t istep = (2 * fx_cb_istep[LR_BST] + 1) / 3;
  fx_acc rr = 0;
  int k;
  for (k = 0; k < NC; k++) {
    fx_acc v = (fx_acc)((2 * target[k] - an[k] - ap[k]) >> 4) * istep;   /* dB Q13 x istep */
    FX_ACC_CHECK(v);
    v >>= 21;
    r[k] = (int16_t)(v > 32767 ? 32767 : v < -32767 ? -32767 : v);
    rr += (fx_acc)r[k] * r[k];
  }
  r[NC] = 0;
  *sb = (int16_t)fx_cb_best(LR_BST, r, rr, hv);
  return b_err(target, an, ap, *sb);
}

static int32_t wgt(int ei) { return ei > 0 ? 10 : 1; }       /* 1.0 and 0.1, x 10 */

static void a_first(lr_coder_t *c, int32_t t, lr_aframe_t *a) {
  const lr_paths_t *q = a_paths(c, t, FR(c, t));
  int i;
  a->p = *FR(c, t);
  for (i = 0; i < LR_NA; i++) a->si[i] = q->path[0][i];
  memcpy(a->rec, q->rec[0], sizeof a->rec);
}

/* Sotto1200._joint for anchor a (frame t): prev = A(s-1) final (or NULL), b0 = B(s-1),
   b1 = B(s), next = A(s+1) first pass (or NULL at the end); b1 = NULL leaves out B(s)'s term
   (LR_AHEAD = 0) */
static void a_joint(lr_coder_t *c, int32_t t, lr_aframe_t *a, const lr_aframe_t *prev, const fx_fparams_t *b0,
                    const fx_fparams_t *b1, const lr_aframe_t *next) {
  const lr_paths_t *q = a_paths(c, t, &a->p);
  int16_t sb;
  int i, best = 0;
  fx_acc bd = 0;
  for (i = 0; i < q->np; i++) {
    fx_acc e = fx_shape_err(a->p.c, q->rec[i]) * wgt(a->p.ei);
    if (prev) e += b_best(b0->c, prev->rec, q->rec[i], &sb) * wgt(b0->ei);
    if (b1) e += b_best(b1->c, q->rec[i], next ? next->rec : q->rec[i], &sb) * wgt(b1->ei);   /* LR_JOINT = 1 */
    FX_ACC_CHECK(e);
    if (i == 0 || e < bd) bd = e, best = i;
  }
  for (i = 0; i < LR_NA; i++) a->si[i] = q->path[best][i];
  memcpy(a->rec, q->rec[best], sizeof a->rec);
}

static int iabs(int x) { return x < 0 ? -x : x; }

/* index of the table entry nearest x (the first of equals), as np.argmin */
static int q_near(const signed char *tab, int n, int x) {
  int b = 0, i;
  for (i = 1; i < n; i++)
    if (iabs(tab[i] - x) < iabs(tab[b] - x)) b = i;
  return b;
}

static int q_near_u(const unsigned char *tab, int n, int x) {
  int b = 0, i;
  for (i = 1; i < n; i++)
    if (iabs(tab[i] - x) < iabs(tab[b] - x)) b = i;
  return b;
}

static int wo_interp(int wa, int va, int wb, int vb) {
  if (va && vb) return (wa + wb + 1) >> 1;
  if (va) return wa;
  if (vb) return wb;
  return -1;
}

/* superframe n = A, B with the next A final */
static void code_superframe(lr_coder_t *c, const lr_aframe_t *a, const fx_fparams_t *b, const lr_aframe_t *nx) {
  lr_fields_t f;
  int i, wint;
  f.ca = a->p.code, f.wa = a->p.wi, f.ea = a->p.ei;
  for (i = 0; i < LR_NA; i++) f.sa[i] = a->si[i];
  f.cb = b->code;
  f.de = (int16_t)q_near(lr_e_tab, 1 << LR_EB_BITS, b->ei - ((a->p.ei + nx->p.ei + 1) >> 1));
  wint = wo_interp(a->p.wi, a->p.code != 0, nx->p.wi, nx->p.code != 0);
  if (b->code == 0) f.dw = LR_W_ZERO;
  else if (wint < 0) f.dw = (int16_t)q_near_u(lr_w_abs, 1 << LR_WB_BITS, b->wi);
  else f.dw = (int16_t)q_near(lr_w_tab, 1 << LR_WB_BITS, b->wi - wint);
  b_best(b->c, a->rec, nx->rec, &f.sb);
  pack(&f, c->out[(c->out_head + c->out_n++) % LR_OUTQ]);
}

/* code every superframe whose look-ahead is in: superframe n needs A(n+1) final, which
   needs frames up to A(n+2) (its joint search looks at A(n+2)'s first pass). With
   -DLR_AHEAD=0 (a lower-delay build, not the float encoder's bits) A(n+1)'s joint search leaves
   out B(n+1) and A(n+2), so superframe n is coded once A(n+1) is in: 80 ms sooner, PESQ about
   -0.02 (with FX_LAG=4, docs/sotto-1200.md) */
#ifndef LR_AHEAD
#define LR_AHEAD 1
#endif
static void drain(lr_coder_t *c) {
  for (;;) {
    int32_t t = c->ncoded;
    int has1, has2;
    const fx_fparams_t *b;
    lr_aframe_t a, n1, n2;
    if (!c->flushed && c->nin < t + (LR_AHEAD ? 5 : 3)) return;   /* A(n), B(n), A(n+1), B(n+1), A(n+2) */
    if (c->nin == t + 1) *FR(c, t + 1) = *FR(c, t), c->nin = t + 2;   /* odd count: B = A */
    if (c->nin < t + 2) return;
    has1 = c->nin >= t + (LR_AHEAD ? 4 : 3), has2 = LR_AHEAD && c->nin >= t + 5;
    b = FR(c, t + 1);
    if (has1) a_first(c, t + 2, &n1);
    if (c->have_prev || (c->first && has1)) a = c->prevA;
    else {                                       /* the first superframe */
      a_first(c, t, &a);
      if (LR_AHEAD) a_joint(c, t, &a, NULL, NULL, b, has1 ? &n1 : NULL);
    }
    if (has1) {
      if (has2) a_first(c, t + 4, &n2);
      a_joint(c, t + 2, &n1, &a, b, LR_AHEAD ? FR(c, t + 3) : NULL, has2 ? &n2 : NULL);
      code_superframe(c, &a, b, &n1);
      c->prevA = n1;
      c->have_prev = 1;
    } else {
      code_superframe(c, &a, b, &a);             /* the last superframe: next = itself */
    }
    c->ncoded = t + 2;
  }
}

/* The first superframe needs A(0), A(1) and A(2)'s searches and A(0)'s joint search, where a
   later one needs one of each: do A(0)'s search when frame 0 comes in, and A(1)'s search and
   A(0)'s joint search (with A(1) as its next, as drain() does whenever B(1) is in) when frame
   2 does, so that no call carries more than a later superframe's work. The same results:
   drain() finds the searches (a_paths keys on the frame) and takes the joint path unless the
   input ends before B(1). */
static void first_ahead(lr_coder_t *c) {
  int32_t t = c->nin - 1;
  if (!LR_AHEAD || c->have_prev || c->first) return;   /* LR_AHEAD = 0 has no such first call */
  if (t == 0) a_paths(c, 0, FR(c, 0));
  else if (t == 2) {
    lr_aframe_t n1;
    a_first(c, 2, &n1);
    a_first(c, 0, &c->prevA);
    a_joint(c, 0, &c->prevA, NULL, NULL, FR(c, 1), &n1);
    c->first = 1;
  }
}

static void coder_push(lr_coder_t *c, const fx_fparams_t *p) {
  *FR(c, c->nin++) = *p;
  drain(c);
  first_ahead(c);
}

static void coder_end(lr_coder_t *c) {
  c->flushed = 1;
  drain(c);
}

static int coder_pop(lr_coder_t *c, unsigned char out[SOTTO_BYTES_PER_FRAME]) {
  if (!c->out_n) return 0;
  memcpy(out, c->out[c->out_head], SOTTO_BYTES_PER_FRAME);
  c->out_head = (int16_t)((c->out_head + 1) % LR_OUTQ);
  c->out_n--;
  return 1;
}

/* ------------------------------------------------------------------ sotto 1200, 8 kHz */
struct sotto_lr_enc {
  struct sotto_enc *core;
  lr_coder_t lr;
};

struct sotto_lr_enc *sotto_lr_enc_create(void) {
  struct sotto_lr_enc *e = calloc(1, sizeof *e);
  if (!e) return NULL;
  e->core = sotto_enc_create();
  if (!e->core) {
    free(e);
    return NULL;
  }
  sotto_enc_set_no_shape(e->core, 1);
  coder_init(&e->lr);
  return e;
}

void sotto_lr_enc_destroy(struct sotto_lr_enc *e) {
  if (!e) return;
  sotto_enc_destroy(e->core);
  free(e);
}

/* sotto 1200 hiss (sotto_lr_enc16 in sotto_fx_hiss.c): the same coder without its core, fed
   the 20 ms frames after v3.8's voicing rules */
struct sotto_lr_enc *sotto_lr_enc_create_frames(void) {
  struct sotto_lr_enc *e = calloc(1, sizeof *e);
  if (e) coder_init(&e->lr);
  return e;
}

void sotto_lr_enc_push(struct sotto_lr_enc *e, const fx_fparams_t *p) { coder_push(&e->lr, p); }
void sotto_lr_enc_end(struct sotto_lr_enc *e) { coder_end(&e->lr); }
int sotto_lr_enc_pop(struct sotto_lr_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) { return coder_pop(&e->lr, out); }
unsigned sotto_fx_lr_coder_bytes(void) { return (unsigned)sizeof(struct sotto_lr_enc); }

/* the state's size with its core, bytes */
unsigned sotto_fx_lr_enc_bytes(void) { return (unsigned)sizeof(struct sotto_lr_enc) + sotto_fx_enc_bytes(); }

static void pull(struct sotto_lr_enc *e) {
  fx_fparams_t p;
  while (sotto_enc_pop_frame_p(e->core, NULL, &p)) coder_push(&e->lr, &p);
}

int sotto_lr_encode(struct sotto_lr_enc *e, const short speech[SOTTO_LR_SAMPLES_PER_FRAME],
                    unsigned char out[SOTTO_BYTES_PER_FRAME]) {
  int i;
  for (i = 0; i < 4; i++) sotto_enc_analyse_block(e->core, speech + 80 * i);
  pull(e);
  return coder_pop(&e->lr, out);
}

void sotto_lr_encode_part(struct sotto_lr_enc *e, const short *speech, int n80) {
  int i;
  for (i = 0; i < n80; i++) sotto_enc_analyse_block(e->core, speech + 80 * i);
  pull(e);
}

int sotto_lr_enc_flush(struct sotto_lr_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) {
  if (!e->lr.flushed) {
    sotto_enc_flush_core(e->core);
    pull(e);
    coder_end(&e->lr);
  }
  return coder_pop(&e->lr, out);
}

/* no fixed-point sotto 600 / 400 encoder */
struct sotto_vlr_enc *sotto_vlr_enc_create(int rate) { (void)rate; return NULL; }
void sotto_vlr_enc_destroy(struct sotto_vlr_enc *e) { (void)e; }
void sotto_vlr_encode(struct sotto_vlr_enc *e, const short *speech, int n80) { (void)e, (void)speech, (void)n80; }
int sotto_vlr_enc_pop(struct sotto_vlr_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) { (void)e, (void)out; return 0; }
int sotto_vlr_enc_flush(struct sotto_vlr_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) { (void)e, (void)out; return 0; }

#ifdef SOTTO_V38
#if defined(FX_HISS_FB) && defined(FX_HISS_NO_ENC)  /* the K6's decoder-only images: no sotto 1200 hiss encoder */
struct sotto_lr_enc16 *sotto_lr_enc16_create(void) { return NULL; }
void sotto_lr_enc16_destroy(struct sotto_lr_enc16 *e) { (void)e; }
int sotto_lr_encode16(struct sotto_lr_enc16 *e, const short speech[SOTTO_LR_SAMPLES_PER_FRAME_16K],
                      unsigned char out[SOTTO_BYTES_PER_FRAME]) { (void)e, (void)speech, (void)out; return 0; }
int sotto_lr_enc16_flush(struct sotto_lr_enc16 *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) { (void)e, (void)out; return 0; }
#endif
#if defined(FX_HISS_LIGHT) && !defined(FX_HISS_FB)   /* sotto_fx_hiss.c has the full layer's (default) or the K6's */
struct sotto_lr_dec16 *sotto_lr_dec16_create(void) { return NULL; }
void sotto_lr_dec16_destroy(struct sotto_lr_dec16 *d) { (void)d; }
void sotto_lr_decode16(struct sotto_lr_dec16 *d, const unsigned char in[SOTTO_BYTES_PER_FRAME], int good,
                       short speech[SOTTO_LR_SAMPLES_PER_FRAME_16K]) { (void)d, (void)in, (void)good, (void)speech; }
int sotto_lr_dec16_flush(struct sotto_lr_dec16 *d, short speech[SOTTO_LR_SAMPLES_PER_FRAME_16K]) { (void)d, (void)speech; return 0; }
#endif

/* no fixed-point sotto 600 / 400 hiss */
struct sotto_vlr_enc16 *sotto_vlr_enc16_create(int rate) { (void)rate; return NULL; }
void sotto_vlr_enc16_destroy(struct sotto_vlr_enc16 *e) { (void)e; }
void sotto_vlr_encode16(struct sotto_vlr_enc16 *e, const short *speech, int n160) { (void)e, (void)speech, (void)n160; }
int sotto_vlr_enc16_pop(struct sotto_vlr_enc16 *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) { (void)e, (void)out; return 0; }
int sotto_vlr_enc16_flush(struct sotto_vlr_enc16 *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) { (void)e, (void)out; return 0; }
#ifndef FX_HISS_FB
struct sotto_vlr_dec16 *sotto_vlr_dec16_create(int rate) { (void)rate; return NULL; }
void sotto_vlr_dec16_destroy(struct sotto_vlr_dec16 *d) { (void)d; }
int sotto_vlr_samples16(const struct sotto_vlr_dec16 *d) { (void)d; return 0; }
void sotto_vlr_decode16(struct sotto_vlr_dec16 *d, const unsigned char in[SOTTO_BYTES_PER_FRAME], int good,
                        short *speech) { (void)d, (void)in, (void)good, (void)speech; }
int sotto_vlr_dec16_flush(struct sotto_vlr_dec16 *d, short *speech) { (void)d, (void)speech; return 0; }
#endif
#endif
