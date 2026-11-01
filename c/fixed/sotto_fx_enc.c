/* sotto encoder in fixed point (integer only), for the C5517 DSP.
 *
 * Same API and, frame for frame, nearly the same bits as the float encoder in ../sotto.c
 * (sotto v3.6). New code, written from the float model's behaviour:
 *  - analysis every 10 ms: Codec 2's 279-point Hann window on a 320-sample buffer and a
 *    512-point FFT, block-normalised and stored as 16-bit complex bins with one exponent;
 *  - Codec 2's NLP pitch estimator (squared signal, DC notch, 600 Hz low-pass, decimate by
 *    5, 64-point Hann, DFT magnitudes, sub-multiple search), its two-stage harmonic-sum
 *    refinement and its MBE voicing decision, which give the tracker its starting pitch;
 *  - sotto's pitch and voicing tracker: candidates at x1, x2 and x1/2 of the neighbouring
 *    frames' pitch, harmonic fit costs, a sub-octave check and a fixed-lag (80 ms) Viterbi,
 *    with costs in natural-log units Q16;
 *  - tail unvoicing and mixed voicing from the harmonic SNR below 1 kHz;
 *  - on even frames, the rate-K envelope and the M-best search of the 8-bit codebook,
 *    and the energy measured on the envelope (v3.6).
 * Where float compares near-equal values (pitch near-ties, bins on a rounding edge) the
 * two can decide differently; tools/check_fx.py counts the frames that differ.
 * SPDX-License-Identifier: MIT */
#define SOTTO_BUILD
#include <stdlib.h>
#include <string.h>
#include "../sotto.h"
#include "fx.h"
#include "fx_tables.h"

#define NSAMP 80
#define MPITCH 320
#define NB 257                 /* stored bins 0..256 of the 512-point spectrum */
#define K FX_K
#define NC FX_NC
#define LAG 8
#ifdef SOTTO_PITCH_THIRD
#define N_MU 4                /* v3.7: also a third of frame t's own estimate */
#else
#define N_MU 3
#endif
#define NCAND 10
#define NST (NCAND + 1)
#define RING 16
#define TAIL_HOLD 30
#define MIXED 2
#define MBEST 8
#define MAXH 80
#define WO_MIN 26843546u      /* 2 pi / 160, Q32 turns */
#define WO_HI 268435456u      /* 2 pi / 16 */
#define WO_C2MAX 214748365u   /* 2 pi / 20, Codec 2's highest pitch */
#define DB(x) ((int32_t)((x) * 256))
#define NAT(x) ((int32_t)((x) * 65536))   /* costs: natural log units, Q16 */
#define LN2_Q16 45426
#define LN_RAD (-1333188)     /* (ln(2 pi) - 32 ln 2), Q16: ln(Wo in radians) from Q32 turns */

#define HIST (NSAMP * RING + MPITCH - NSAMP)   /* input kept, so a decided frame's spectrum can be redone */

typedef struct {
  int16_t sw[2 * NB];         /* spectrum, re/im interleaved, 16 bits */
  int16_t e;                  /* exponent: float spectrum = sw x 2^(e + fx_sw_l2 / 2^16) */
  uint32_t p[NB];             /* power per bin, normalised to 31 bits, for the pitch searches */
} spec_t;

typedef struct {
  uint32_t wo0;               /* Codec 2's Wo (NLP + two-stage refinement) */
  int16_t v0;                 /* Codec 2's voicing */
  int16_t nc;
  uint32_t cand[NCAND];
  int32_t lnc[NCAND];         /* ln(candidate Wo), Q16 */
  int32_t cost[NST];
  int32_t D[NST];             /* best path cost ending in each state, less the frame's minimum */
  unsigned char back[NST];
} frame_t;

struct sotto_enc {
  int16_t hist[HIST];         /* input; the last MPITCH samples are the analysis buffer */
  spec_t spec[2];             /* spectra of the last two frames, for the tracker */
  int32_t re[512], im[512];   /* FFT scratch */
  /* NLP */
  int32_t sq[MPITCH], mem_x, mem_y, fir[48];
  int16_t sh, blk[4];         /* NLP block floating point: values are true x 2^-sh */
  int16_t prev_bin;
  frame_t ring[RING];
  int32_t n_an, n_dec;
  int32_t ehist[TAIL_HOLD + 1];
  /* even half of the frame being built */
  uint32_t wo_e;
  int32_t en_e;
  int16_t idx_e[5], cls_e;
  unsigned char q[8][SOTTO_BYTES_PER_FRAME];
  int16_t q_head, q_n, flushed;
};

#define R(e, t) (&(e)->ring[(t) % RING])

static int32_t ln_q16(uint64_t x) { return (int32_t)(((fx_acc)fx_log2_64(x) * LN2_Q16 + 32768) >> 16); }
static int32_t ln_wo(uint32_t wo) { return ln_q16(wo) + LN_RAD; }
/* 2^48 / x: pitch period Q16 <-> Wo Q32 turns */
static uint32_t recip48(uint32_t x) { return (uint32_t)((((uint64_t)1 << 48) + (x >> 1)) / x); }

/* power of bin b (0..511) of frame f's 16-bit spectrum */
static fx_acc pw(const spec_t *f, int b) {
  if (b > 256) b = 512 - b;
  return (fx_acc)f->sw[2 * b] * f->sw[2 * b] + (fx_acc)f->sw[2 * b + 1] * f->sw[2 * b + 1];
}
/* the same at 31-bit precision (sums of up to 256 stay inside 40 bits), for harmonic sums */
static fx_acc pwh(const spec_t *f, int b) { return f->p[b > 256 ? 512 - b : b]; }

/* Codec 2's harmonic count: floor(pi / Wo), less one when the last harmonic is at 0.95 pi or above */
static int n_harm(uint32_t wo) {
  int L = (int)(0x80000000u / wo);
  if ((uint64_t)L * wo >= 2040109466u) L--;
  return L;
}

/* ceil((2l - 1) Wo 256 / 2^32) style bin bounds: ceil(x / 2^sh) and floor(x / 2^sh + 1/2) */
static int ceil_sh(uint64_t x, int sh) { return (int)((x + ((uint64_t)1 << sh) - 1) >> sh); }
static int round_sh(uint64_t x, int sh) { return (int)((x + ((uint64_t)1 << (sh - 1))) >> sh); }

/* ---------------------------------------------------------------- analysis */

/* Codec 2's windowed 512-point spectrum of the 320 samples at buf: e->re, e->im (int32,
   float spectrum = re x 2^(return value + fx_sw_l2 / 2^16)), and its 16-bit copy in *f */
static int spectrum(struct sotto_enc *e, const int16_t *buf, spec_t *f) {
  int32_t *re = e->re, *im = e->im;
  int32_t x[278];
  uint32_t mx = 0;
  for (int i = 0; i < 278; i++) {
    x[i] = (int32_t)buf[21 + i] * fx_hann[i];                /* Q15 */
    uint32_t a = (uint32_t)(x[i] < 0 ? -x[i] : x[i]);
    if (a > mx) mx = a;
  }
  memset(re, 0, sizeof e->re);
  memset(im, 0, sizeof e->im);
  int s = 0;                                                  /* x * 2^-s, largest in [2^22, 2^23) */
  if (mx) {
    while ((mx >> s) >= (1u << 23)) s++;
    if (s == 0)
      while (((uint64_t)mx << (1 - s)) < (1u << 23)) s--;
  }
  /* Codec 2 centres the window on the time origin: samples 160..298 at 0.., 21..159 at the end */
  for (int i = 0; i < 278; i++) {
    int n = 21 + i;                                           /* buffer index */
    re[n >= 160 ? n - 160 : 512 - 160 + n] = s > 0 ? fx_rshr(x[i], s) : x[i] * (1 << -s);
  }
  fx_fft(re, im, 512);
  int32_t m2 = 0;
  for (int b = 0; b < NB; b++) {
    int32_t a = re[b] < 0 ? -re[b] : re[b], c = im[b] < 0 ? -im[b] : im[b];
    if (a > m2) m2 = a;
    if (c > m2) m2 = c;
  }
  int s2 = 0;
  if (m2) {
    while ((m2 >> s2) > 32767) s2++;
    if (s2 == 0)
      while (s2 > -15 && ((int64_t)m2 << (1 - s2)) <= 32767) s2--;
  }
  for (int b = 0; b < NB; b++) {
    f->sw[2 * b] = (int16_t)(s2 > 0 ? fx_rshr(re[b], s2) : re[b] * (1 << -s2));
    f->sw[2 * b + 1] = (int16_t)(s2 > 0 ? fx_rshr(im[b], s2) : im[b] * (1 << -s2));
  }
  f->e = (int16_t)(s + s2);
  int64_t pm = 0;                                             /* 64-bit squares of 32-bit bins */
  for (int b = 0; b < NB; b++) {
    int64_t q = (int64_t)re[b] * re[b] + (int64_t)im[b] * im[b];
    if (q > pm) pm = q;
  }
  int sp = 0;
  while ((pm >> sp) >= ((int64_t)1 << 31)) sp++;
  for (int b = 0; b < NB; b++)
    f->p[b] = (uint32_t)((((int64_t)re[b] * re[b] + (int64_t)im[b] * im[b]) + (sp ? (int64_t)1 << (sp - 1) : 0)) >> sp);
  return s;
}

/* Codec 2's NLP: the pitch bin (3.125 Hz steps) of the 10 ms just added to the input */
static int msb(uint32_t x) { int n = -1; while (x) { x >>= 1; n++; } return n; }
static uint32_t uabs(int32_t x) { return (uint32_t)(x < 0 ? -x : x); }
static int32_t shift(int64_t x, int s) { return s > 0 ? fx_rshr(x, s) : (int32_t)(x * ((int64_t)1 << -s)); }

static int nlp_bin(struct sotto_enc *e) {
  /* squared input; choose this block's exponent so it and the filter memories stay below
     2^22, and rescale the memories to it */
  uint32_t sq2[NSAMP], mx = 0, mm = uabs(e->mem_x) | uabs(e->mem_y);
  for (int i = 0; i < NSAMP; i++) {
    int32_t v = e->hist[HIST - NSAMP + i];
    sq2[i] = (uint32_t)(v * v);
    mx |= sq2[i];
  }
  for (int j = 0; j < 48; j++) mm |= uabs(e->fir[j]);
  int sh = msb(mx) - 21, shm = mm ? e->sh + msb(mm) - 21 : -99;
  if (shm > sh) sh = shm;
  if (sh < -8) sh = -8;
  int d = sh - e->sh;
  e->mem_x = shift(e->mem_x, d);
  e->mem_y = shift(e->mem_y, d);
  for (int j = 0; j < 48; j++) e->fir[j] = shift(e->fir[j], d);
  e->sh = (int16_t)sh;
  e->blk[3] = (int16_t)sh;
  int32_t one = shift(1, sh);                                 /* Codec 2 adds 1.0 after the notch */
  for (int i = 0; i < NSAMP; i++) {
    int32_t x = shift(sq2[i], sh);
    int32_t y = x - e->mem_x + fx_rshr((fx_acc)e->mem_y * 31130, 15);   /* DC notch, pole 0.95 */
    e->mem_x = x;
    e->mem_y = y;
    memmove(e->fir, e->fir + 1, 47 * sizeof(int32_t));
    e->fir[47] = y + one;
    fx_acc a = 0;
    for (int j = 0; j < 48; j++) a += (fx_acc)e->fir[j] * fx_nlp_fir[j];
    FX_ACC_CHECK(a);
    e->sq[MPITCH - NSAMP + i] = fx_rshr(a, 15);
  }
  /* decimate by 5 (aligning the four blocks' exponents), window, normalise to 15 bits */
  int shx = e->blk[0];
  for (int b = 1; b < 4; b++)
    if (e->blk[b] > shx) shx = e->blk[b];
  int32_t xd[64];
  mx = 0;
  for (int i = 0; i < 64; i++) {
    int32_t v = shift(e->sq[5 * i], shx - e->blk[(5 * i) / NSAMP]);
    xd[i] = fx_rshr((fx_acc)v * fx_nlp_win[i], 15);
    mx |= uabs(xd[i]);
  }
  int s = 0;
  while ((mx >> s) >= (1u << 14)) s++;
  int16_t x16[64];
  for (int i = 0; i < 64; i++) x16[i] = (int16_t)(s ? fx_rshr(xd[i], s) : xd[i]);
  /* DFT magnitudes at bins 15..129 of 512 */
  fx_acc P[130];                                          /* entries 15..129 used */
  for (int k = 15; k < 130; k++) {
    fx_acc r = 0, q = 0;
    for (int n = 0; n < 64; n++) {
      int x = (k * n) & 511;
      r += (fx_acc)x16[n] * fx_cos512[x];
      q += (fx_acc)x16[n] * fx_cos512[(x - 128) & 511];
    }
    FX_ACC_CHECK(r); FX_ACC_CHECK(q);
    int32_t rr = fx_rshr(r, 15), qq = fx_rshr(q, 15);
    P[k] = (fx_acc)rr * rr + (fx_acc)qq * qq;              /* 64-bit scalar */
  }
  fx_acc gmax = 0;
  int gbin = 16;
  for (int k = 16; k <= 128; k++)
    if (P[k] > gmax) gmax = P[k], gbin = k;
  /* sub-multiples: prefer a lower pitch peak that is a local maximum above a threshold,
     a lower threshold near the previous frame's estimate */
  int cbin = gbin;
  for (int mult = 2; gbin / mult >= 16; mult++) {
    int b = gbin / mult, bmin = fx_nlp_bmin[b], bmax = fx_nlp_bmax[b];
    if (bmin < 16) bmin = 16;
    int near = e->prev_bin > bmin && e->prev_bin < bmax;
    fx_acc lmax = 0;
    int lbin = bmin;
    for (b = bmin; b <= bmax; b++)
      if (P[b] > lmax) lmax = P[b], lbin = b;
    /* lmax > 0.3 gmax, or 0.15 gmax near the previous estimate */
    if ((near ? 20 * lmax > 3 * gmax : 10 * lmax > 3 * gmax) && lmax > P[lbin - 1] && lmax > P[lbin + 1])
      cbin = lbin;
  }
  e->prev_bin = (int16_t)cbin;
  memmove(e->sq, e->sq + NSAMP, (MPITCH - NSAMP) * sizeof(int32_t));
  memmove(e->blk, e->blk + 1, 3 * sizeof(int16_t));
  return cbin;
}

/* Codec 2's harmonic-sum refinement over pitch periods p0 - span .. p0 + span (Q16) */
static uint32_t hs_refine(const spec_t *f, uint32_t p0, uint32_t span, uint32_t step, uint32_t wo) {
  int L = (int)(0x80000000u / wo);
  fx_acc em = 0;
  uint32_t wom = wo;
  for (uint32_t p = p0 - span; p <= p0 + span; p += step) {
    uint32_t w = recip48(p);
    fx_acc E = 0;
    for (int m = 1; m <= L; m++) E += pwh(f, round_sh((uint64_t)m * w, 23));
    FX_ACC_CHECK(E);
    if (E > em) em = E, wom = w;
  }
  return wom;
}

/* least-squares fit of the window response to bins [al, bl) around harmonic l:
   returns the residual power, and the band power in *sig */
static fx_acc harm_fit(const spec_t *f, uint32_t wo, int l, fx_acc *sig) {
  int al = ceil_sh((uint64_t)(2 * l - 1) * wo, 24), bl = ceil_sh((uint64_t)(2 * l + 1) * wo, 24);
  int off = (int)((((uint64_t)256 << 23) + (1u << 22) - (uint64_t)l * wo) >> 23);
  fx_acc nr = 0, ni = 0, den = 0, s = 0, err = 0;
  for (int i = al; i < bl; i++) {
    int32_t w = fx_W[off + i];
    nr += (fx_acc)f->sw[2 * i] * w;
    ni += (fx_acc)f->sw[2 * i + 1] * w;
    den += (fx_acc)w * w;
  }
  FX_ACC_CHECK(nr); FX_ACC_CHECK(ni); FX_ACC_CHECK(den);
  if (den > 0) {
    int32_t ar = (int32_t)(nr * 32768 / den), ai = (int32_t)(ni * 32768 / den);   /* Q15, 64-bit scalar */
    for (int i = al; i < bl; i++) {
      int32_t w = fx_W[off + i];
      int32_t er = f->sw[2 * i] - fx_rshr((fx_acc)ar * w, 15), ei = f->sw[2 * i + 1] - fx_rshr((fx_acc)ai * w, 15);
      err += (fx_acc)er * er + (fx_acc)ei * ei;
      s += pw(f, i);
    }
    FX_ACC_CHECK(err); FX_ACC_CHECK(s);
  }
  if (sig) *sig = s;
  return err;
}

/* Codec 2's MBE voicing decision at its refined Wo */
static int c2_voicing(const spec_t *f, uint32_t wo) {
  int L = n_harm(wo);
  fx_acc A2[MAXH + 1];
  for (int m = 1; m <= L; m++) {
    int am = round_sh((uint64_t)(2 * m - 1) * wo, 24), bm = round_sh((uint64_t)(2 * m + 1) * wo, 24);
    fx_acc p = 0;
    for (int i = am; i < bm; i++) p += pw(f, i);
    A2[m] = p;
  }
  int l1 = L / 4;
  fx_acc sig = 0, err = 0;
  for (int l = 1; l <= l1; l++) {
    sig += A2[l];
    err += harm_fit(f, wo, l, NULL);
  }
  int v = sig * 65536 > err * 260904;                       /* SNR > 6 dB */
  fx_acc lo = 0, hi = 0;
  for (int l = 1; l <= L / 2; l++) lo += A2[l];
  for (int l = L / 2; l <= L; l++) hi += A2[l];
  if (!v && lo > 10 * hi) v = 1;                            /* low/high ratio > 10 dB */
  if (v) {
    if (10 * lo < hi) v = 0;                                /* < -10 dB */
    if (lo * 164619 < hi * 65536 && wo <= 32212254u) v = 0; /* < -4 dB at a pitch of 60 Hz or less */
  }
  return v;
}

/* ---------------------------------------------------------------- tracker */

/* sotto's two-stage refinement (sinusoid.refine), clamped to [WO_MIN, wo_max] */
static uint32_t refine(const spec_t *f, uint32_t wo, uint32_t wo_max) {
  static const uint32_t span[2] = {5u << 16, 1u << 16}, step[2] = {1u << 16, 1u << 14};
  static const int np[2] = {11, 9};
  uint32_t p0 = recip48(wo);
  for (int s = 0; s < 2; s++) {
    int L = (int)(p0 >> 17);                                /* floor(pi / Wo) */
    fx_acc best = -1;
    uint32_t pbest = p0;
    for (int i = 0; i < np[s]; i++) {
      uint32_t p = p0 - span[s] + (uint32_t)i * step[s], w = recip48(p);
      fx_acc E = 0;
      for (int m = 1; m <= L; m++) {
        int b = round_sh((uint64_t)m * w, 23);
        if (b < 256) E += pwh(f, b);
      }
      FX_ACC_CHECK(E);
      if (E > best) best = E, pbest = p;
    }
    p0 = pbest;
  }
  uint32_t w = recip48(p0);
  return w < WO_MIN ? WO_MIN : w > wo_max ? wo_max : w;
}

/* sinusoid.fit_error, as a natural log, Q16 */
static int32_t ln_fit_error(const spec_t *f, uint32_t wo) {
  int L = (int)(1342177280u / wo);                          /* 2500 Hz / f0 */
  if (L < 1) L = 1;
  int hi = ceil_sh((uint64_t)(2 * L + 1) * wo, 24);
  fx_acc err = 0, en = 0;
  for (int l = 1; l <= L; l++) err += harm_fit(f, wo, l, NULL);
  for (int i = 1; i < hi; i++) en += pw(f, i);
  if (en == 0) return 0;
  return ln_q16((uint64_t)(err > 0 ? err : 1)) - ln_q16((uint64_t)en);
}

/* sinusoid.odd_even_db, dB Q8 */
static int32_t odd_even_db(const spec_t *f, uint32_t wo) {
  int h = (int)(wo >> 25);
  if (h < 1) h = 1;
  int L = (int)(805306368u / wo);                           /* 1500 Hz / f0 */
  fx_acc odd = 0, even = 0;
  for (int j = 3; j <= L; j++) {
    int c = (int)(((uint64_t)j * wo) >> 23);
    fx_acc p = 0;
    if (c < 256)
      for (int i = c - h > 1 ? c - h : 1; i <= c + h; i++) {
        fx_acc q = pwh(f, i);
        if (q > p) p = q;
      }
    if (j % 2) odd += p; else even += p;
  }
  return fx_log2_to_db_pow(fx_log2_64((uint64_t)(odd > 0 ? odd : 1)) - fx_log2_64((uint64_t)(even > 0 ? even : 1)));
}

/* candidates and costs of frame t */
static void frame_costs(struct sotto_enc *e, int32_t t, int has_next) {
  frame_t *f = R(e, t);
  const spec_t *sp = &e->spec[t & 1];
  static const int dd[3] = {0, -1, 1};
  f->nc = 0;
  for (int i = 0; i < 3; i++) {
    int32_t u = t + dd[i];
    if (u < 0 || (dd[i] == 1 && !has_next)) continue;
    uint32_t base = R(e, u)->wo0;
    for (int j = 0; j < (dd[i] == 0 ? N_MU : 3); j++) {
      if (j == 3 && base < 112742892u) continue;              /* base / 3 below 70 Hz */
      uint64_t w0 = j == 0 ? base : j == 1 ? (uint64_t)base * 2 : j == 2 ? (base + 1) >> 1 : ((uint64_t)base + 1) / 3;
      uint32_t w0c = w0 < WO_MIN ? WO_MIN : w0 > WO_HI ? WO_HI : (uint32_t)w0;
      uint32_t w = refine(sp, w0c, WO_HI);
      if (w >= 37580964u || (dd[i] == 0 && j == 0)) {        /* 70 Hz */
        int dup = 0;
        for (int c = 0; c < f->nc; c++) {                    /* |ln(w / cand)| <= 0.01 */
          uint64_t a = f->cand[c];
          if ((uint64_t)w * 1000000 <= a * 1010050 && a * 1000000 <= (uint64_t)w * 1010050) dup = 1;
        }
        if (!dup) f->cand[f->nc++] = w;
      }
    }
  }
  f->cost[0] = NAT(-0.5) + NAT(1.0) * (f->v0 > 0);
  for (int c = 0; c < f->nc; c++) {
    uint32_t w = f->cand[c];
    f->lnc[c] = ln_wo(w);
    int32_t cst = ln_fit_error(sp, w) - f->lnc[c] / 2 + NAT(1.0) * (f->v0 == 0);
    int32_t oe = odd_even_db(sp, w);
    if (-oe - DB(10) > 0) cst += (int32_t)(((fx_acc)(-oe - DB(10)) * 512) / 10);   /* 2 (-oe - 10) / 10 */
    f->cost[1 + c] = cst;
  }
}

static void viterbi_step(struct sotto_enc *e, int32_t t) {
  frame_t *f = R(e, t);
  int n = f->nc + 1;
  if (t == 0) {
    for (int j = 0; j < n; j++) f->D[j] = f->cost[j], f->back[j] = 0;
  } else {
    frame_t *p = R(e, t - 1);
    int np = p->nc + 1;
    for (int j = 0; j < n; j++) {
      int32_t best = 0;
      int bi = 0;
      for (int i = 0; i < np; i++) {
        int32_t tr;
        if (i == 0 && j == 0) tr = 0;
        else if (i == 0 || j == 0) tr = NAT(1.5);
        else {
          int32_t lj = p->lnc[i - 1] - f->lnc[j - 1], x;
          if (lj < 0) lj = -lj;
          x = lj - 15142;                                    /* ln 2 / 3 */
          tr = 3 * lj + 4 * (x > 0 ? x : 0);
        }
        int32_t tot = p->D[i] + tr;
        if (i == 0 || tot < best) best = tot, bi = i;
      }
      f->D[j] = best + f->cost[j];
      f->back[j] = (unsigned char)bi;
    }
  }
  int32_t mn = f->D[0];                                      /* keep D small: argmins don't change */
  for (int j = 1; j < n; j++)
    if (f->D[j] < mn) mn = f->D[j];
  for (int j = 0; j < n; j++) f->D[j] -= mn;
}

/* ---------------------------------------------------------------- frame decision */

static void put_bits(unsigned char *out, int *pos, int v, int nb) {
  for (int i = nb - 1; i >= 0; i--, (*pos)++)
    if ((v >> i) & 1) out[*pos >> 3] |= 0x80 >> (*pos & 7);
}

/* M-best multistage search; c in dB Q16 */
static void msvq_search(const int32_t *c, int16_t *idx) {
  int np = 1;
  int16_t path[MBEST][5];
  int32_t recon[MBEST][NC];                                  /* dB Q16 */
  memset(recon, 0, sizeof recon);
  memset(path, 0, sizeof path);
  for (int s = 0; s < fx_cb_stages; s++) {
    int n = 1 << fx_cb_bits[s], nk = 0;
    const int8_t *cb = fx_cb[s];
    const int32_t *e2 = fx_cb_e2[s];
    fx_acc kd[MBEST];
    int kp[MBEST], kc[MBEST];
    for (int p = 0; p < np; p++) {
      int16_t r[NC];                                         /* residual in codebook steps, Q6 */
      fx_acc rr = 0;
      for (int k = 0; k < NC; k++) {
        fx_acc t = ((fx_acc)(c[k] - recon[p][k]) * fx_cb_istep[s]) >> 24;
        r[k] = (int16_t)(t > 32767 ? 32767 : t < -32767 ? -32767 : t);
        rr += (fx_acc)r[k] * r[k];
      }
      FX_ACC_CHECK(rr);
      /* d = sum (r - 64 y)^2 = rr - 128 r.y + 4096 |y|^2, exactly, so the inner loop is one
         16 x 16 multiply-accumulate per value */
      for (int v = 0; v < n; v++) {
        const int8_t *y = cb + v * NC;
        fx_acc ry = 0;
        for (int k = 0; k < NC; k++) ry += (fx_acc)r[k] * y[k];
        FX_ACC_CHECK(ry);
        fx_acc d = rr - 128 * ry + 4096 * (fx_acc)e2[v];   /* < 2^36 */
        FX_ACC_CHECK(d);
        if (nk < MBEST || d < kd[nk - 1]) {
          int i = nk < MBEST ? nk++ : MBEST - 1;
          while (i > 0 && kd[i - 1] > d) kd[i] = kd[i - 1], kp[i] = kp[i - 1], kc[i] = kc[i - 1], i--;
          kd[i] = d, kp[i] = p, kc[i] = v;
        }
      }
    }
    int16_t npath[MBEST][5];
    int32_t nrec[MBEST][NC];
    for (int i = 0; i < nk; i++) {
      memcpy(npath[i], path[kp[i]], sizeof path[0]);
      npath[i][s] = (int16_t)kc[i];
      for (int k = 0; k < NC; k++) nrec[i][k] = recon[kp[i]][k] + (int32_t)cb[kc[i] * NC + k] * fx_cb_step[s];
    }
    memcpy(path, npath, sizeof path);
    memcpy(recon, nrec, sizeof recon);
    np = nk;
  }
  int best = 0;
  fx_acc bd = 0;
  for (int p = 0; p < np; p++) {
    fx_acc d = 0;
    for (int k = 0; k < NC; k++) {
      int32_t q = fx_rshr(c[k] - recon[p][k], 8);
      d += (fx_acc)q * q;
    }
    if (p == 0 || d < bd) bd = d, best = p;
  }
  memcpy(idx, path[best], fx_cb_stages * sizeof(int16_t));
}

/* envelope (dB Q8) at f (Hz Q4), as the decoder's */
static int32_t env_at(const int32_t *rk, int32_t f) {
  if (f <= fx_kfreq[0]) return rk[0];
  if (f >= fx_kfreq[K - 1]) return rk[K - 1];
  int j = 0;
  while (fx_kfreq[j + 1] < f) j++;
  int32_t fr = (int32_t)(((fx_acc)(f - fx_kfreq[j]) * fx_kinvw[j]) >> 16);
  return rk[j] + (int32_t)(((fx_acc)(rk[j + 1] - rk[j]) * fr + 32768) >> 16);
}

/* 10 log10 of a power in units of a spectrum with exponent ex, as absolute dB Q8 */
static int32_t power_db(int ex, int64_t p) {
  if (p <= 0) return DB(-90);
  return fx_log2_to_db_pow(fx_log2_64((uint64_t)p) + 2 * ((int32_t)ex * 65536 + fx_sw_l2));
}

static void emit(struct sotto_enc *e, int cls);

static void decide(struct sotto_enc *e, int32_t t, int k) {
  frame_t *f = R(e, t);
  uint32_t wo = k ? f->cand[k - 1] : f->wo0;
  int L = n_harm(wo);
  /* redo frame t's spectrum from the kept input, at 32 bits for the harmonic levels */
  spec_t spx, *sp = &spx;
  int ex = spectrum(e, e->hist + HIST - MPITCH - (e->n_an - 1 - t) * NSAMP, sp);
  int64_t A2[MAXH + 1], tot = 0;                              /* 64-bit sums of 32 x 32-bit squares */
  for (int h = 1; h <= L; h++) {
    int am = round_sh((uint64_t)(2 * h - 1) * wo, 24), bm = round_sh((uint64_t)(2 * h + 1) * wo, 24);
    int64_t p = 0;
    for (int i = am; i < bm; i++) {
      int b = i > 256 ? 512 - i : i;
      p += (int64_t)e->re[b] * e->re[b] + (int64_t)e->im[b] * e->im[b];
    }
    A2[h] = p;
    tot += p;
  }
  int32_t en = power_db(ex, tot);

  /* unvoice_tails, then voicing_classes */
  e->ehist[t % (TAIL_HOLD + 1)] = en;
  int cls = k > 0;
  if (cls) {
    int32_t emax = INT32_MIN;
    for (int32_t u = t - TAIL_HOLD < 0 ? 0 : t - TAIL_HOLD; u <= t; u++)
      if (e->ehist[u % (TAIL_HOLD + 1)] > emax) emax = e->ehist[u % (TAIL_HOLD + 1)];
    /* mean harmonic SNR below 1 kHz, dB Q8 */
    int32_t snr = INT32_MAX, sum = 0, n = 0;
    for (int l = 1; l <= L; l++) {
      if ((uint64_t)l * wo * 8000 >= (uint64_t)1000 << 32) break;
      fx_acc sig, err = harm_fit(sp, wo, l, &sig);
      sum += sig > 0 ? fx_log2_to_db_pow(fx_log2_64((uint64_t)sig) - fx_log2_64((uint64_t)(err > 0 ? err : 1))) : 0;
      n++;
    }
    if (n) snr = sum / n;
    if (en < emax - DB(20) && snr < DB(6)) cls = 0;
    else if (snr < DB(8)) cls = MIXED;
  }

  if (t % 2 == 0) {
    int32_t a[MAXH], amax = INT32_MIN, rk[K];
    for (int h = 1; h <= L; h++) {
      a[h - 1] = A2[h] > 0 ? power_db(ex, A2[h]) : DB(-320);
      if (a[h - 1] > amax) amax = a[h - 1];
    }
    for (int h = 0; h < L; h++)
      if (a[h] < amax - DB(50)) a[h] = amax - DB(50);
    /* np.interp of the harmonic levels at the rate-K frequencies (harmonic h at h f0) */
    for (int j = 0; j < K; j++) {
      int64_t u = ((int64_t)fx_kfreq[j] << 41) / ((int64_t)wo * 1000);   /* in harmonics, Q16 */
      int32_t ui = (int32_t)(u >> 16), fr = (int32_t)(u & 0xFFFF);
      if (ui < 1) rk[j] = a[0];
      else if (ui >= L) rk[j] = a[L - 1];
      else rk[j] = a[ui - 1] + (int32_t)(((fx_acc)(a[ui] - a[ui - 1]) * fr + 32768) >> 16);
    }
    int32_t sum = 0, c[NC];
    for (int i = 0; i < K; i++) sum += rk[i];
    for (int j = 1; j < K; j++) {                            /* DCT of rk - mean, dB Q16 */
      fx_acc v = 0;
      for (int i = 0; i < K; i++) v += (fx_acc)fx_dct[j * K + i] * (rk[i] * 20 - sum);
      FX_ACC_CHECK(v);
      c[j - 1] = fx_rshr(v / 20, 7);                         /* Q8 x Q15 x 20 -> dB Q16 */
    }
    msvq_search(c, e->idx_e);
    e->wo_e = wo;
    /* v3.6: energy of the envelope at the harmonics */
    int32_t lv[MAXH];
    for (int h = 1; h <= L; h++) lv[h - 1] = env_at(rk, (int32_t)(((uint64_t)h * wo * 128000u) >> 32));
    e->en_e = fx_db_power_sum(lv, L);
    e->cls_e = (int16_t)cls;
  } else {
    emit(e, cls);
  }
}

static void emit(struct sotto_enc *e, int cls) {
  int a = e->cls_e, b = cls, code = a == b ? a : (a == 0 || b == 0) ? 3 : 1;
  unsigned char *out = e->q[(e->q_head + e->q_n++) % 8];
  int pos = 0, wi = 0, ei;
  while (wi < 127 && fx_wo_thr[wi] <= e->wo_e) wi++;
  int32_t num = (e->en_e - DB(10)) * 31;                     /* rint((en - 10) / 70 x 31) */
  ei = num <= 0 ? 0 : (int)((num + 8960) / 17920);
  if (ei > 31) ei = 31;
  memset(out, 0, SOTTO_BYTES_PER_FRAME);
  put_bits(out, &pos, code, 2);
  put_bits(out, &pos, wi, 7);
  put_bits(out, &pos, ei, 5);
  for (int s = 0; s < fx_cb_stages; s++) put_bits(out, &pos, e->idx_e[s], fx_cb_bits[s]);
}

static void decide_from(struct sotto_enc *e, int32_t t, int32_t last) {
  frame_t *f = R(e, last);
  int k = 0;
  for (int j = 1; j <= f->nc; j++)
    if (f->D[j] < f->D[k]) k = j;
  for (int32_t u = last; u > t; u--) k = R(e, u)->back[k];
  decide(e, t, k);
}

/* ---------------------------------------------------------------- API */

struct sotto_enc *sotto_enc_create(void) {
  struct sotto_enc *e = calloc(1, sizeof *e);
  if (!e) return NULL;
  for (int i = 0; i < HIST; i++) e->hist[i] = 1;
  e->prev_bin = 16;                                          /* 50 Hz */
  return e;
}

void sotto_enc_destroy(struct sotto_enc *e) { free(e); }

static void analyse_10ms(struct sotto_enc *e, const short *x) {
  memmove(e->hist, e->hist + NSAMP, (HIST - NSAMP) * sizeof(int16_t));
  for (int i = 0; i < NSAMP; i++) e->hist[HIST - NSAMP + i] = x[i];
  int32_t a = e->n_an++;
  frame_t *f = R(e, a);
  spec_t *sp = &e->spec[a & 1];
  int bin = nlp_bin(e);
  spectrum(e, e->hist + HIST - MPITCH, sp);
  /* Codec 2: Wo = 2 pi / pitch, pitch = 2560 / bin samples; two-stage refinement */
  uint32_t p0 = (uint32_t)((((uint64_t)2560 << 16) + bin / 2) / bin);
  uint32_t wo = recip48(p0);
  wo = hs_refine(sp, p0, 5u << 16, 1u << 16, wo);
  wo = hs_refine(sp, recip48(wo), 1u << 16, 1u << 14, wo);
  if (wo < WO_MIN) wo = WO_MIN;
  if (wo > WO_C2MAX) wo = WO_C2MAX;
  f->wo0 = wo;
  f->v0 = (int16_t)c2_voicing(sp, wo);
  if (a >= 1) {
    frame_costs(e, a - 1, 1);
    viterbi_step(e, a - 1);
    if (a - 1 - LAG >= 0) decide_from(e, e->n_dec++, a - 1);
  }
}

static int pop(struct sotto_enc *e, unsigned char *out) {
  if (!e->q_n) return 0;
  memcpy(out, e->q[e->q_head], SOTTO_BYTES_PER_FRAME);
  e->q_head = (int16_t)((e->q_head + 1) % 8);
  e->q_n--;
  return 1;
}

int sotto_encode(struct sotto_enc *e, const short speech[SOTTO_SAMPLES_PER_FRAME],
                 unsigned char out[SOTTO_BYTES_PER_FRAME]) {
  analyse_10ms(e, speech);
  analyse_10ms(e, speech + NSAMP);
  return pop(e, out);
}

void sotto_encode_half(struct sotto_enc *e, const short speech[SOTTO_SAMPLES_PER_FRAME / 2]) {
  analyse_10ms(e, speech);
}

int sotto_enc_flush(struct sotto_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]) {
  if (!e->flushed && e->n_an > 0) {
    int32_t n = e->n_an;
    frame_costs(e, n - 1, 0);
    viterbi_step(e, n - 1);
    while (e->n_dec < n) decide_from(e, e->n_dec++, n - 1);
    if (n % 2) emit(e, e->cls_e);
    e->flushed = 1;
  }
  return pop(e, out);
}
