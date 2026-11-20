/* sotto 1200 slim encoder (docs/sotto-slim.md): ordinary sotto 1200 superframes from an
 * analysis light enough for a Cortex-M0 with a few KB of RAM (the Baofeng UV-K6).
 *
 * Where the full encoder (sotto_fx_enc.c) fits harmonics to a 512-point spectrum every 10 ms
 * for ten pitch candidates, this one
 *  - finds pitch in the time domain: the input low-passed and decimated to 4 kHz, a
 *    normalised cross-correlation over lags 8..80 every 10 ms, up to SL_NCAND peaks, and a
 *    small Viterbi over them (SL_D halves of look-ahead) that also makes the voicing call;
 *  - measures the envelope once per 20 ms frame: a 256-point Hann window, a 16-bit 256-point
 *    FFT, the power summed in a band around each harmonic, as the full encoder's levels;
 *  - searches the shape codebook by cells (slim_cells.h: the target against a stage's
 *    centroids, then only the vectors of the PROBE nearest cells; -DSLIM_FULL_SEARCH compares
 *    every vector), keeps PATHS candidates for an A frame and takes the one that suits the B
 *    frame before it too (the full encoder: 8 paths, the B frames on both sides, the next A).
 * Arithmetic is 16 x 16 -> 32 bits throughout (no 64-bit products, three divisions a lag
 * search aside), state is slim_enc_bytes().
 * SPDX-License-Identifier: MIT */
#include <string.h>
#include "sotto_slim.h"
#include "fx_tables.h"
#include "../sotto_lr_tables.h"
#ifndef SLIM_FULL_SEARCH
#define SLIM_IVF
#include "slim_cells.h"
#define IVF_MAXP 8
#endif

#define NC SLIM_NC
#define K 20
#define HOP 80
#define NW 256                     /* envelope window */
#define NX4 240                    /* 4 kHz history */
#define S4 204                     /* 4 kHz samples a lag search reads */
#define W4 120                     /* its window */
#define LMIN 8                     /* lags at 4 kHz: 500 Hz .. */
#define LMAX 80                    /* .. 50 Hz */
#define NL (LMAX - LMIN + 3)       /* scores kept: lags LMIN - 1 .. LMAX + 1 */
#define SL_NCAND 4
#ifndef SL_D
#define SL_D 2                     /* halves of look-ahead in the pitch decision */
#endif
#define RING (SL_D + 1)
#define NX8 (HOP * (SL_D + 2) + NW / 2 + HOP)   /* 8 kHz history: the decided even half's window */
#define TAIL 30
#define MAXH 80
#define DB(x) ((int32_t)((x) * 256L))
#define P8_UV (80 * 16)            /* unvoiced frames: bands 100 Hz apart */

#ifdef SLIM_TUNE
#include <stdio.h>
int slim_tune[32] = {
  /*  0 LAGW  */ 450,   /* lag taper: score x (1 - LAGW/1024 x lag / 81) */
  /*  1 VOB   */ 614,   /* unvoiced cost = VOB + best score, Q10 */
  /*  2 TUV   */ 100,   /* voiced <-> unvoiced transition, Q10 */
  /*  3 FW    */ 1200,  /* pitch change: FW/1024 x |log2 ratio| */
  /*  4 THV   */ 820,   /* voiced (not mixed) from this correlation, Q10 */
  /*  5 THT   */ 820,   /* quiet tails below this go unvoiced, Q10 */
  /*  6 CAL   */ 1088,  /* level offset, dB Q8 */
  /*  7 QMIN  */ 200,   /* candidates from this correlation, Q10 */
  /*  8 SUB2  */ 2,     /* lag search stride over the window */
  /*  9 DBLC  */ 300,   /* octave jump allowance, Q10 */
  /* 10 HPS   */ 3,     /* pitch path high-pass: one pole, time constant 2^HPS samples at 4 kHz (0: off) */
  /* 11 TLW   */ 307,   /* unvoiced cost falls TLW/256 per unit of tl (the more energy above 1 kHz) */
  /* 12 PW    */ 100,   /* a candidate costs PW/1024 per octave from the talker's usual pitch */
  /* 13 PSH   */ 4,     /* the usual pitch follows strongly voiced halves with time constant 2^PSH */
  /* 14 PROBE */ 3,     /* codebook cells searched a stage */
  /* 15 PATHS */ 2,     /* paths of an A frame's shape search (1: no joint choice) */
  /* 16 UVBW  */ 2,     /* an unvoiced frame's bands: UVBW x 100 Hz wide */
  /* 17 HUM   */ 4,     /* hum: no pitch when the window's first difference has under 2^-HUM of its energy (0: off) */
};
long slim_stat[4];      /* bench counters: vectors compared, searches, codebook vectors read */
#define T(i, v) slim_tune[i]
/* bench: frame n's voicing code and pitch index taken from elsewhere (slim_ovr[2 n], [2 n + 1]) */
const int16_t *slim_ovr;
int slim_ovr_n;
#else
#define T(i, v) (v)
#endif
#define LAGW T(0, 450)
#define VOB T(1, 614)
#define TUV T(2, 100)
#define FW T(3, 1200)
#define THV T(4, 820)
#define THT T(5, 820)
#define CAL T(6, 1088)
#define QMIN T(7, 200)
#define SUB2 T(8, 2)
#define DBLC T(9, 300)
#define HPS T(10, 3)
#define TLW T(11, 307)
#define PW T(12, 100)
#define PSH T(13, 4)
#define PROBE T(14, 3)
#define PATHS T(15, 2)
#define UVBW T(16, 2)
#define HUM T(17, 4)
#define SLIM_MAXP 4
#ifdef SLIM_TUNE
#define STAT(i, n) (slim_stat[i] += (n))
#else
#define STAT(i, n) ((void)0)
#endif

typedef struct {
  int16_t lag[SL_NCAND];           /* 4 kHz lag, Q4 */
  int16_t n[SL_NCAND];             /* correlation there less the lag taper, Q10 */
  int16_t nr[SL_NCAND];            /* the correlation itself */
  int16_t l2[SL_NCAND];            /* log2(lag), Q10 */
  int16_t D[SL_NCAND + 1];         /* best path cost ending in each state (0: unvoiced) */
  unsigned char back[SL_NCAND + 1];
  unsigned char nc;
  int16_t el2;                     /* log2 of the half's energy, Q8 */
  int16_t tl;                      /* log2 of the share of its energy below 1 kHz, Q8 (<= 0) */
} half_t;

struct slim_enc {
  /* working memory, free between calls: the envelope's FFT (re, im), or the lag search's
     running sums of squares (205 x 32 bits); and the harmonic levels, or the lag scores */
  int16_t w[2 * NW];
  int16_t a[MAXH];
  int16_t x8[NX8];                 /* input, newest last */
  int16_t x4[NX4];                 /* low-passed, at 4 kHz */
  int32_t dc;                      /* input DC estimate, Q8 */
  int32_t hp;                      /* the pitch path's high-pass state, Q8 */
  int32_t t;                       /* 10 ms blocks in */
  int32_t ndec;                    /* halves decided */
  half_t ring[RING];
  int16_t ehist[TAIL + 1];
  int16_t pavg, pav_ok;            /* the talker's usual lag: log2 as half_t.l2, and whether it's set */
  /* the even half of the frame being built */
  int16_t cls_e, wi_e;
  slim_frame_t fe;
  int16_t aflush;
  /* coder */
  int32_t nfr;                     /* frames in */
  slim_frame_t fa, fb;             /* A(n) and B(n) waiting for A(n + 1) */
  int16_t sa[2], have_a, have_b;
  int16_t ra[NC];                  /* A(n)'s reconstruction, dB Q8 */
  int16_t cflush;
};

unsigned slim_enc_bytes(void) { return (unsigned)sizeof(struct slim_enc); }

/* ------------------------------------------------------------------ small maths */
static int iabs(int x) { return x < 0 ? -x : x; }

/* round(1024 log2(1 + i / 32)) */
static const int16_t l2tab[33] = {
  0, 45, 90, 133, 174, 215, 254, 292, 330, 366, 402, 436, 470, 503, 536, 567, 599,
  629, 659, 688, 717, 745, 773, 800, 827, 853, 879, 905, 930, 954, 979, 1002, 1024};
/* round(2^20 2^(-i / 32)) */
static const int32_t e2tab[33] = {
  1048576, 1026107, 1004119, 982603, 961548, 940944, 920781, 901051, 881744, 862850, 844361,
  826268, 808563, 791237, 774283, 757692, 741456, 725568, 710021, 694807, 679919, 665350,
  651093, 637141, 623489, 610129, 597055, 584262, 571742, 559491, 547502, 535771, 524288};

static int msb32(uint32_t x) {
  int n = 0;
  if (x >> 16) n += 16, x >>= 16;
  if (x >> 8) n += 8, x >>= 8;
  if (x >> 4) n += 4, x >>= 4;
  if (x >> 2) n += 2, x >>= 2;
  if (x >> 1) n += 1;
  return n;
}

/* 1024 log2(x), x >= 1 */
static int32_t log2_q10(uint32_t x) {
  int n = msb32(x);
  uint32_t m = n >= 15 ? x >> (n - 15) : x << (15 - n);      /* [2^15, 2^16) */
  int i = (int)((m >> 10) & 31), f = (int)(m & 1023);
  return (int32_t)n * 1024 + l2tab[i] + (((l2tab[i + 1] - l2tab[i]) * f + 512) >> 10);
}

/* 10 log10(p) in dB Q8 (p = 0: as p = 1) */
static int32_t db_q8(uint32_t p) { return (log2_q10(p ? p : 1) * 24661 + 16384) >> 15; }

/* 10 log10 of the sum of 10^(v / 10) over n levels v (dB Q8) */
static int32_t db_power_sum(const int16_t *v, int n) {
  int i;
  int32_t mx = v[0];
  uint32_t s = 0;
  for (i = 1; i < n; i++) mx = v[i] > mx ? v[i] : mx;
  for (i = 0; i < n; i++) {
    int32_t k = ((mx - v[i]) * 1361) >> 10;                  /* log2 units, Q10 */
    int ki = (int)(k >> 10), kf = (int)(k & 1023), j = kf >> 5, f = kf & 31;
    if (ki < 20) s += (uint32_t)(e2tab[j] + (((e2tab[j + 1] - e2tab[j]) * f) >> 5)) >> ki;
  }
  return mx + db_q8(s) - 15412;                              /* less 10 log10(2^20) */
}

static uint32_t isqrt32(uint32_t x) {
  uint32_t r = 0, b = (uint32_t)1 << 30;
  while (b > x) b >>= 2;
  while (b) {
    if (x >= r + b) x -= r + b, r = (r >> 1) + b;
    else r >>= 1;
    b >>= 2;
  }
  return r;
}

/* sin(2 pi k / 256), Q15, k = 0..64 */
static const int16_t sin256[65] = {
  0, 804, 1608, 2410, 3212, 4011, 4808, 5602, 6393, 7179, 7962, 8739, 9512, 10278, 11039,
  11793, 12539, 13279, 14010, 14732, 15446, 16151, 16846, 17530, 18204, 18868, 19519, 20159,
  20787, 21403, 22005, 22594, 23170, 23731, 24279, 24811, 25329, 25832, 26319, 26790, 27245,
  27683, 28105, 28510, 28898, 29268, 29621, 29956, 30273, 30571, 30852, 31113, 31356, 31580,
  31785, 31971, 32137, 32285, 32412, 32521, 32609, 32678, 32728, 32757, 32767};
static int cos256(int i) {                                   /* cos(2 pi i / 256), i = 0..255 */
  i &= 255;
  if (i > 128) i = 256 - i;
  return i <= 64 ? sin256[64 - i] : -sin256[i - 64];
}
static int sn256(int i) { return cos256(i - 64); }

/* in-place 256-point FFT of 16-bit values, halved at every stage: the DFT / 256 */
static void fft256(int16_t *re, int16_t *im) {
  int i, j, k, len, sh;
  for (i = 1, j = 0; i < 256; i++) {
    int bit = 128;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      int16_t t = re[i];
      re[i] = re[j], re[j] = t;
      t = im[i], im[i] = im[j], im[j] = t;
    }
  }
  for (len = 2, sh = 7; len <= 256; len <<= 1, sh--) {
    int half = len >> 1;
    for (k = 0; k < half; k++) {
      int32_t wr = cos256(k << sh), wi = -sn256(k << sh);
      for (i = k; i < 256; i += len) {
        int32_t tr, ti, ar = re[i], ai = im[i];
        j = i + half;
        tr = (re[j] * wr - im[j] * wi + 16384) >> 15;
        ti = (re[j] * wi + im[j] * wr + 16384) >> 15;
        re[j] = (int16_t)((ar - tr) >> 1), im[j] = (int16_t)((ai - ti) >> 1);
        re[i] = (int16_t)((ar + tr) >> 1), im[i] = (int16_t)((ai + ti) >> 1);
      }
    }
  }
}

/* ------------------------------------------------------------------ envelope */
/* fx_dct row j (1..19), column i: a platform short of memory may compute it instead
   (round(32768 sqrt(2/20) cos(pi (2i + 1) j / 40)), 21 distinct magnitudes) */
#ifndef SLIM_DCT
#define SLIM_DCT(j, i) fx_dct[(j) * K + (i)]
#endif
/* The frame's envelope and energy from the 256 samples at x, for pitch period p8 (8 kHz
   samples, Q4): the shape c (DCT coefficients 1..19, dB Q8) and the energy code. */
static void envelope(slim_enc_t *e, const int16_t *x, int32_t p8, slim_frame_t *f) {
  int16_t *re = e->w, *im = e->w + NW, *a = e->a, rk[K];
  int i, h, j, sh = 0, L, bw;
  int32_t mx = 0, amax, sum = 0, mean, en;
  uint32_t binstep;
  for (i = 0; i < NW; i++) {
    int32_t v = x[i] < 0 ? -(int32_t)x[i] : x[i];
    if (v > mx) mx = v;
  }
  memset(f->c, 0, sizeof f->c);
  f->ei = 0;
  if (mx == 0) return;
  while ((mx << sh) < 16384) sh++;                           /* largest in [2^14, 2^15) */
  for (i = 0; i < NW; i++) {
    int32_t w = 16384 - (cos256(i) >> 1);                    /* Hann, Q15 */
    re[i] = (int16_t)((((int32_t)x[i] << sh) * w + 16384) >> 15);
    im[i] = 0;
  }
  fft256(re, im);
  /* harmonic h's level: the power in the bins nearest (h - 1/2) f0 .. (h + 1/2) f0 */
  L = (int)(p8 >> 5);                                        /* floor(P / 2) */
  if ((int32_t)L * 640 >= 19 * p8) L--;                      /* the last one at 0.95 pi or above */
  if (L > MAXH) L = MAXH;
  if (L < 1) L = 1;
  binstep = ((uint32_t)256 << 20) / (uint32_t)p8;            /* bins a harmonic, Q16 */
  amax = -32768;
  bw = p8 == P8_UV ? UVBW : 1;                               /* noise: wider bands, a steadier level */
  for (h = 1; h <= L; h++) {
    int am = (int)(((uint32_t)(2 * h - bw) * binstep + 65536u) >> 17);
    int bm = (int)(((uint32_t)(2 * h + bw) * binstep + 65536u) >> 17);
    uint32_t p = 0;
    int32_t v;
    if (bm > 129) bm = 129;
    for (i = am; i < bm; i++) p += (uint32_t)((int32_t)re[i] * re[i]) + (uint32_t)((int32_t)im[i] * im[i]);
    if (bw > 1) p /= (uint32_t)bw;
    v = db_q8(p) - 1541 * sh + CAL;
    if (v < -32768) v = -32768;
    if (v > 32767) v = 32767;
    a[h - 1] = (int16_t)v;
    if (v > amax) amax = v;
  }
  for (h = 0; h < L; h++)
    if (a[h] < amax - DB(50)) a[h] = (int16_t)(amax - DB(50));
  /* the levels interpolated at the rate-K frequencies (harmonic h at h f0) */
  for (j = 0; j < K; j++) {
    uint32_t u = ((uint32_t)fx_kfreq[j] * (uint32_t)p8 * 8u) / 250u;   /* harmonics, Q16 */
    int ui = (int)(u >> 16);
    int32_t fr = (int32_t)((u >> 4) & 0xFFF);
    if (ui < 1) rk[j] = a[0];
    else if (ui >= L) rk[j] = a[L - 1];
    else rk[j] = (int16_t)(a[ui - 1] + (((a[ui] - a[ui - 1]) * fr + 2048) >> 12));
    sum += rk[j];
  }
  mean = (sum + (sum >= 0 ? K / 2 : -(K / 2))) / K;
  for (j = 1; j < K; j++) {
    int32_t v = 0;
    for (i = 0; i < K; i++) v += ((rk[i] - mean) >> 1) * SLIM_DCT(j, i);
    v = (v + 8192) >> 14;
    f->c[j - 1] = (int16_t)(v > 32767 ? 32767 : v < -32767 ? -32767 : v);
  }
  /* the energy of the envelope at the harmonics, as the decoder will read it back */
  {
    int16_t *lv = a;                                         /* the levels aren't needed any more */
    int32_t f0 = (int32_t)(2048000u / (uint32_t)p8), fh = f0;   /* Hz Q4 */
    int32_t slope = 0;
    int seg = -1;
    j = 0;
    for (h = 0; h < L; h++, fh += f0) {
      if (fh <= fx_kfreq[0]) lv[h] = rk[0];
      else if (fh >= fx_kfreq[K - 1]) lv[h] = rk[K - 1];
      else {
        while (fx_kfreq[j + 1] < fh) j++;
        if (seg != j) slope = ((int32_t)(rk[j + 1] - rk[j]) << 12) / (fx_kfreq[j + 1] - fx_kfreq[j]), seg = j;
        lv[h] = (int16_t)(rk[j] + ((slope * (fh - fx_kfreq[j]) + 2048) >> 12));
      }
    }
    en = db_power_sum(lv, L);
  }
  {
    int32_t num = (en - DB(10)) * 31;
    int ei = num <= 0 ? 0 : (int)((num + 8960) / 17920);
    f->ei = (int16_t)(ei > 31 ? 31 : ei);
  }
}

/* ------------------------------------------------------------------ pitch */
/* 7-bit pitch index of a period of p8 8 kHz samples (Q4): 127 log10(f0 / 50 Hz), rounded */
static int wo_index(int32_t p8) {
  /* log2(160 / P) x 127 / log2(10) */
  int32_t l = log2_q10(160u * 16u) - log2_q10((uint32_t)p8);
  int wi = (int)((l * 9787 + (1 << 17)) >> 18);              /* 127 / 3.3219 / 1024 x 2^18 */
  return wi < 0 ? 0 : wi > 127 ? 127 : wi;
}

/* the lag search of one half: the candidates of h from the 4 kHz samples s[0..S4). The
   correlation at lag L is over a window of W4 samples centred with its shifted copy on the
   half: the cross term from every SUB2-th product, the two energies from running sums. */
static void lag_search(slim_enc_t *e, const int16_t *s, half_t *h) {
  uint32_t *cs = (uint32_t *)(void *)e->w;                   /* cs[i]: sum of the squares before sample i */
  int16_t *q = e->a;
  int i, L, sh = 0, c, k;
  int32_t mx = 0;
  uint32_t acc = 0;
  for (i = 0; i < S4; i++) {
    int32_t v = s[i] < 0 ? -(int32_t)s[i] : s[i];
    if (v > mx) mx = v;
  }
  while ((mx >> sh) >= 2048) sh++;                           /* as 12 bits: sums of 120 products fit */
  sh *= 2;
  for (i = 0; i < S4; i++) cs[i] = acc, acc += (uint32_t)((int32_t)s[i] * s[i]) >> sh;
  cs[S4] = acc;
  acc = cs[(S4 + W4) / 2] - cs[(S4 - W4) / 2];
  h->el2 = (int16_t)(acc ? (log2_q10(acc) >> 2) + 256 * sh : 0);   /* log2 of the energy, Q8 */
  h->nc = 0;
  /* Mains hum is as periodic as a voice, but nearly all of it lies below 200 Hz: when the
     first difference of the window (-20 dB at 60 Hz, -2 dB at 500 Hz) holds less than
     2^-HUM of its energy, there is no voice to find a pitch for. */
  if (HUM) {
    uint32_t dsum = 0;
    for (i = (S4 - W4) / 2 + 1; i < (S4 + W4) / 2; i++) {
      uint32_t v = (uint32_t)iabs(s[i] - s[i - 1]);         /* up to 65,535: its square fits 32 bits unsigned */
      dsum += (v * v) >> sh;
    }
    if (dsum < acc >> HUM) return;
  }
  for (L = LMIN - 1; L <= LMAX + 1; L++) {
    int a0 = (S4 - W4 - L) / 2;
    const int16_t *p0 = s + a0, *p1 = p0 + L;
    int32_t r = 0;
    uint32_t e0 = cs[a0 + W4] - cs[a0], e1 = cs[a0 + L + W4] - cs[a0 + L], m, d;
    int n;
    for (i = 0; i < W4; i += SUB2) r += ((int32_t)p0[i] * p1[i]) >> sh;
    r *= SUB2;
    q[L - LMIN + 1] = 0;
    if (r <= 0) continue;
    m = e0 > e1 ? e0 : e1;
    if ((uint32_t)r > m) r = (int32_t)m;                     /* the sparse cross term can overshoot */
    n = msb32(m) - 14;
    if (n < 0) n = 0;
    d = ((e0 >> n) * (e1 >> n)) >> 12;
    if (d < 16) continue;                                    /* silence */
    r >>= n;
    d = (uint32_t)(r * r) / d;                               /* the correlation squared, Q12 */
    q[L - LMIN + 1] = (int16_t)(d > 4096 ? 4096 : d);
  }
  /* the best SL_NCAND local maxima */
  for (L = LMIN; L <= LMAX; L++) {
    int y0 = q[L - LMIN + 1], ym = q[L - LMIN], yp = q[L - LMIN + 2], n, lag;
    int32_t den;
    if (y0 <= ym || y0 < yp) continue;
    n = (int)isqrt32((uint32_t)y0 << 8);                     /* Q10 */
    if (n < QMIN) continue;
    den = ym - 2 * y0 + yp;
    lag = L * 16 + (den < 0 ? (int)((8 * (ym - yp)) / den) : 0);
    k = n;
    n = n - ((n * LAGW >> 10) * L) / (LMAX + 1);            /* lag taper: prefer the shorter period */
    c = h->nc;
    if (c == SL_NCAND) {                                     /* replace the weakest */
      for (c = 0, i = 1; i < SL_NCAND; i++)
        if (h->n[i] < h->n[c]) c = i;
      if (h->n[c] >= n) continue;
    } else h->nc++;
    h->lag[c] = (int16_t)lag, h->n[c] = (int16_t)n, h->nr[c] = (int16_t)k;
    h->l2[c] = (int16_t)(log2_q10((uint32_t)lag) - 4096);
  }
}

static void viterbi(slim_enc_t *e, int32_t p) {
  half_t *h = &e->ring[p % RING];
  int i, j, best = 0;
  int32_t cu, mn;
  for (j = 0; j < h->nc; j++)
    if (h->n[j] > best) best = h->n[j];
  cu = VOB + best + ((TLW * h->tl) >> 8);
  if (e->pav_ok)                                             /* the talker's usual pitch is likelier */
    for (j = 0; j < h->nc; j++) {
      int32_t d = h->l2[j] - e->pavg;
      h->n[j] = (int16_t)(h->n[j] - (((d < 0 ? -d : d) * PW) >> 10));
    }
  if (p == 0) {
    h->D[0] = (int16_t)cu, h->back[0] = 0;
    for (j = 0; j < h->nc; j++) h->D[j + 1] = (int16_t)(1024 - h->n[j]), h->back[j + 1] = 0;
  } else {
    const half_t *g = &e->ring[(p - 1) % RING];
    for (j = 0; j <= h->nc; j++) {
      int32_t bd = 0;
      int bi = 0;
      for (i = 0; i <= g->nc; i++) {
        int32_t tr;
        if (i == 0 && j == 0) tr = 0;
        else if (i == 0 || j == 0) tr = TUV;
        else {
          int32_t d = g->l2[i - 1] - h->l2[j - 1], d2;
          if (d < 0) d = -d;
          d2 = d > 1024 ? d - 1024 : 1024 - d;               /* an octave jump */
          if (d2 + DBLC < d) d = d2 + DBLC;
          tr = (d * FW) >> 10;
        }
        tr += g->D[i];
        if (i == 0 || tr < bd) bd = tr, bi = i;
      }
      bd += j ? 1024 - h->n[j - 1] : cu;
      h->D[j] = (int16_t)(bd > 32000 ? 32000 : bd);
      h->back[j] = (unsigned char)bi;
    }
  }
  mn = h->D[0];
  for (j = 1; j <= h->nc; j++)
    if (h->D[j] < mn) mn = h->D[j];
  for (j = 0; j <= h->nc; j++) h->D[j] = (int16_t)(h->D[j] - mn);
}

/* half d's state on the best path ending at half last */
static int backtrack(const slim_enc_t *e, int32_t d, int32_t last) {
  const half_t *h = &e->ring[last % RING];
  int k = 0, j;
  int32_t u;
  for (j = 1; j <= h->nc; j++)
    if (h->D[j] < h->D[k]) k = j;
  for (u = last; u > d; u--) k = e->ring[u % RING].back[k];
  return k;
}

/* half d is decided (state k of its candidates): its class, and on odd halves the frame.
   x8end: the 8 kHz index one past the newest sample in e->x8 is 80 x (blocks in). */
static int decide(slim_enc_t *e, int32_t d, int k, slim_frame_t *f) {
  const half_t *h = &e->ring[d % RING];
  int cls = 0, u, wi;
  int32_t p8 = P8_UV, emax = -32768;
  e->ehist[d % (TAIL + 1)] = h->el2;
  if (k > 0) {
    int n = h->nr[k - 1];
    p8 = 2 * h->lag[k - 1];
    cls = n >= THV ? 1 : 2;
    if (cls == 1) {
      if (!e->pav_ok) e->pavg = h->l2[k - 1], e->pav_ok = 1;
      else e->pavg = (int16_t)(e->pavg + ((h->l2[k - 1] - e->pavg) >> PSH));
    }
    for (u = d - TAIL < 0 ? 0 : d - TAIL; u <= d; u++)
      if (e->ehist[u % (TAIL + 1)] > emax) emax = e->ehist[u % (TAIL + 1)];
    if (h->el2 < emax - 1701 && n < THT) cls = 0, p8 = P8_UV;   /* 20 dB down: 6.64 in log2, Q8 */
  }
  wi = wo_index(p8);
#ifdef SLIM_TUNE
  if (slim_ovr && d / 2 < slim_ovr_n) {
    /* the period of pitch index wi: 160 x 10^(-wi / 127) samples */
    static const double l10 = 2.302585092994046;
    extern double exp(double);
    int w = slim_ovr[2 * (d / 2) + 1], c = slim_ovr[2 * (d / 2)];
    if (d % 2 == 0) {
      p8 = (int32_t)(160.0 * 16.0 * exp(-l10 * w / 127.0) + 0.5);
      if (c == 0) p8 = P8_UV;
    }
  }
#endif
#ifdef SLIM_TUNE
  if (slim_tune[31]) {
    int c;
    fprintf(stderr, "H %d k=%d cls=%d wi=%d el2=%d tl=%d |", (int)d, k, cls, wi, h->el2, h->tl);
    for (c = 0; c < h->nc; c++) fprintf(stderr, " %d:%d/%d(%d)", wo_index(2 * h->lag[c]), h->nr[c], h->n[c], h->D[c + 1]);
    fprintf(stderr, " U(%d)\n", h->D[0]);
  }
#endif
  if (d % 2 == 0) {
    /* the window centred on 80 (d - 1): the newest sample is 80 t - 1 */
    int32_t c = 80 * (d - 1), end = 80 * e->t;
    const int16_t *x = e->x8 + NX8 - (end - (c - NW / 2));
    envelope(e, x, p8, &e->fe);
    e->cls_e = (int16_t)cls, e->wi_e = (int16_t)wi;
    return 0;
  }
  {
    int a = e->cls_e, b = cls;
    *f = e->fe;
    f->code = (int16_t)(a == b ? a : (a == 0 || b == 0) ? 3 : 1);
    f->wi = (int16_t)(a == 0 && b != 0 ? wi : e->wi_e);
#ifdef SLIM_TUNE
    if (slim_ovr && d / 2 < slim_ovr_n) f->code = slim_ovr[2 * (d / 2)], f->wi = slim_ovr[2 * (d / 2) + 1];
#endif
  }
  return 1;
}

void slim_enc_init(slim_enc_t *e) {
  memset(e, 0, sizeof *e);
}

int slim_analyse10(slim_enc_t *e, const int16_t x[HOP], slim_frame_t *f) {
  int i, r = 0;
  int32_t u = e->t++, p;
  memmove(e->x8, e->x8 + HOP, (NX8 - HOP) * sizeof(int16_t));
  for (i = 0; i < HOP; i++) {
    int32_t v = ((int32_t)x[i] << 8) - e->dc;
    e->dc += v >> 6;
    v >>= 8;
    e->x8[NX8 - HOP + i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
  }
  /* 4 kHz: x4[m] = sum_k h[k] x8[2 m + k], h = (1 2 3 4 3 2 1) / 16, m up to 40 u + 38 */
  memmove(e->x4, e->x4 + HOP / 2, (NX4 - HOP / 2) * sizeof(int16_t));
  for (i = 0; i < HOP / 2; i++) {
    const int16_t *c = e->x8 + NX8 - HOP - 2 + 2 * i;        /* x8[2 m], m = 40 u - 1 + i */
    int32_t v = (c[-3] + c[3] + 2 * (c[-2] + c[2]) + 3 * (c[-1] + c[1]) + 4 * c[0] + 8) >> 4;
    if (HPS) {
      int32_t d = (v << 8) - e->hp;
      e->hp += d >> HPS;
      v = d >> 8;
    }
    e->x4[NX4 - HOP / 2 + i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
  }
  p = u - 1;                                                 /* the half the lag search can reach */
  if (p < 0) return 0;
  /* its centre is 4 kHz sample 40 (p - 1); x4's newest is 40 u + 38 */
  lag_search(e, e->x4 + NX4 - 1 - (40 * u + 38 - (40 * (p - 1) - S4 / 2)), &e->ring[p % RING]);
  {   /* the share of the half's energy below 1 kHz: 20 ms around its centre, both rates */
    const int16_t *a = e->x8 + NX8 - 4 * HOP, *b = e->x4 + NX4 - 1 - 118 - HOP / 2;
    uint32_t e8 = 0, e4 = 0;
    for (i = 0; i < 2 * HOP; i++) e8 += (uint32_t)(((int32_t)a[i] * a[i]) >> 8);
    for (i = 0; i < HOP; i++) e4 += (uint32_t)(((int32_t)b[i] * b[i]) >> 7);
    e->ring[p % RING].tl = (int16_t)((log2_q10(e4 + 1) - log2_q10(e8 + 1)) >> 2);
  }
  viterbi(e, p);
  if (p - SL_D >= 0) {
    int32_t d = e->ndec++;
    r = decide(e, d, backtrack(e, d, p), f);
  }
  return r;
}

int slim_analyse_flush(slim_enc_t *e, slim_frame_t *f) {
  /* a block of silence, so the last half gets its lag search; then the halves still in the
     look-ahead, decided from it */
  int32_t last;
  if (!e->aflush) {
    int16_t z[HOP];
    memset(z, 0, sizeof z);
    e->aflush = 1;
    if (slim_analyse10(e, z, f)) return 1;
  }
  last = e->t - 2;
  while (e->ndec <= last) {
    int32_t d = e->ndec++;
    if (decide(e, d, backtrack(e, d, last), f)) return 1;
  }
  if (e->aflush == 1 && (e->ndec & 1)) {                     /* an odd count: the last half repeated */
    e->aflush = 2;
    *f = e->fe;
    f->code = e->cls_e, f->wi = e->wi_e;
    return 1;
  }
  return 0;
}

/* ------------------------------------------------------------------ coder */
static void put_bits(unsigned char *out, int *pos, int v, int nb) {
  int i;
  for (i = nb - 1; i >= 0; i--, (*pos)++)
    if ((v >> i) & 1) out[*pos >> 3] |= (unsigned char)(0x80 >> (*pos & 7));
}

/* Vector v of stage s as the 20 bytes of its 10 packed words in a little-endian memory (the
   K6's codebook image in SPI flash, c/k6/sp_cb.c): value k is byte k ^ 1, and byte 18 is the
   pad, 0. SLIM_CB_FETCH(s, v, buf) may copy it to buf (20 bytes) or point into a table. */
#ifndef SLIM_CB_FETCH
#define SLIM_CB_FETCH(s, v, buf) ((void)(buf), (const signed char *)(const void *)(fx_cb[s] + (v) * 10))
#endif
#define CBB 20

#ifdef SLIM_IVF
/* The cells (slim_cells.h), through two hooks a platform may replace to keep the tables
   elsewhere (the K6 reads them from SPI flash):
   SLIM_IVF_CEN(s, c0, buf): centroids c0 .. c0 + IVF_BLK - 1 of stage s, IVF_CD bytes each,
     copied to buf (IVF_BLK * IVF_CD bytes) or pointed at;
   SLIM_IVF_CELL(s, c, v): the numbers of the vectors in cell c of stage s into v (at most
     IVF_MAXN), rising; returns how many. */
#define IVF_BLK 16
#ifndef SLIM_IVF_CEN
#define SLIM_IVF_CEN(s, c0, buf) \
  ((void)(buf), ((s) == 0 ? ivf_cen0 : (s) == 1 ? ivf_cen1 : ivf_cen2) + (c0) * IVF_CD)
#endif
#ifndef SLIM_IVF_CELL
#define SLIM_IVF_CELL(s, c, v) ivf_cell(s, c, v)
static int ivf_cell(int s, int c, int16_t *v) {
  const uint16_t *off = s == 0 ? ivf_off0 : s == 1 ? ivf_off1 : ivf_off2;
  const unsigned char *idx = s == 0 ? ivf_idx0 : s == 1 ? ivf_idx1 : ivf_idx2;
  int n = off[c + 1] - off[c], lo = s == 0 ? ivf_lo0[c] : s == 1 ? ivf_lo1[c] : n, i;
  for (i = 0; i < n; i++) v[i] = (int16_t)(idx[off[c] + i] + (i >= lo ? 256 : 0));
  return n;
}
#endif
#endif

/* sum of y (32 y - t) over a vector's bytes: its squared distance from t, less |t|^2, / 128 */
static int32_t cb_hn(const signed char *y, const int16_t *t, int n) {
  int32_t hsum = 0;
  int k;
  for (k = 0; k < n; k++) hsum += y[k] * (32 * y[k] - t[k]);
  return hsum;
}
static int32_t cb_h(const signed char *y, const int16_t *t) { return cb_hn(y, t, CBB); }

/* the nb vectors of stage s nearest the residual r (dB Q8) over gain num / den, nearest
   first, into best; returns how many (nb, or fewer from a small cell) */
static int cb_search(int s, const int16_t *r, int num, int den, int16_t *best, int nb) {
  int16_t t[CBB];
  signed char buf[CBB];
  int32_t bh[SLIM_MAXP];
  int n = 1 << fx_cb_bits[s], v, k, nf = 0, i;
  int32_t istep = (fx_cb_istep[s] * den) / num;
  int32_t lim = 0x7FFFFFFF / istep;
  t[18] = 0;
  for (k = 0; k < NC; k++) {                                 /* in codebook steps, Q6, in byte order */
    int32_t x = r[k] > lim ? lim : r[k] < -lim ? -lim : r[k];
    x = (x * istep) >> 16;
    t[k ^ 1] = (int16_t)(x > 32767 ? 32767 : x < -32767 ? -32767 : x);
  }
#define KEEP(hsum, v) \
  if (nf < nb || (hsum) < bh[nf - 1]) { \
    i = nf < nb ? nf++ : nf - 1; \
    while (i > 0 && bh[i - 1] > (hsum)) bh[i] = bh[i - 1], best[i] = best[i - 1], i--; \
    bh[i] = (hsum), best[i] = (int16_t)(v); \
  }
#ifdef SLIM_IVF
  {
    /* the PROBE cells whose centroids are nearest, then their vectors */
    int nc = s == 0 ? IVF_C0 : s == 1 ? IVF_C1 : IVF_C2, np = 0, c, c0, j, nv;
    int32_t ph[IVF_MAXP];
    unsigned char pc[IVF_MAXP];
    signed char cbuf[IVF_BLK * IVF_CD];
    int16_t vl[IVF_MAXN];
    int probe = PROBE > IVF_MAXP ? IVF_MAXP : PROBE;
    (void)n, (void)cbuf;
    for (c0 = 0; c0 < nc; c0 += IVF_BLK) {
      const signed char *cen = SLIM_IVF_CEN(s, c0, cbuf);
      for (c = c0; c < c0 + IVF_BLK; c++, cen += IVF_CD) {
        int32_t hsum = cb_hn(cen, t, IVF_CD);
        if (np < probe || hsum < ph[np - 1]) {
          i = np < probe ? np++ : np - 1;
          while (i > 0 && ph[i - 1] > hsum) ph[i] = ph[i - 1], pc[i] = pc[i - 1], i--;
          ph[i] = hsum, pc[i] = (unsigned char)c;
        }
      }
    }
    STAT(0, nc), STAT(1, 1);
    for (j = 0; j < np; j++) {
      nv = SLIM_IVF_CELL(s, pc[j], vl);
      for (c = 0; c < nv; c++) {
        int32_t hsum;
        v = vl[c];
        hsum = cb_h(SLIM_CB_FETCH(s, v, buf), t);
        KEEP(hsum, v)
        STAT(0, 1), STAT(2, 1);
      }
    }
  }
#else
  for (v = 0; v < n; v++) {
    int32_t hsum = cb_h(SLIM_CB_FETCH(s, v, buf), t);
    KEEP(hsum, v)
  }
  STAT(0, n), STAT(1, 1), STAT(2, n);
#endif
#undef KEEP
  return nf;
}

/* r less vector v of stage s times num / den; returns what is left, the sum of (r / 8)^2 */
static int32_t cb_sub(int s, int v, int16_t *r, int num, int den) {
  signed char buf[CBB];
  const signed char *y = SLIM_CB_FETCH(s, v, buf);
  int32_t step = (fx_cb_step[s] * num) / den, d = 0;
  int k;
  STAT(2, 1);
  for (k = 0; k < NC; k++) {
    int32_t x = r[k] - ((y[k ^ 1] * step + 128) >> 8);
    r[k] = (int16_t)x;
    x >>= 3;
    d += x * x;
  }
  return d;
}

static int q_near(const signed char *tab, int x) {
  int b = 0, i;
  for (i = 1; i < 8; i++)
    if (iabs(tab[i] - x) < iabs(tab[b] - x)) b = i;
  return b;
}
static int q_near_u(const unsigned char *tab, int x) {
  int b = 0, i;
  for (i = 1; i < 8; i++)
    if (iabs(tab[i] - x) < iabs(tab[b] - x)) b = i;
  return b;
}

/* a path of an A frame's shape search: stages 1 and 2, its reconstruction and its error */
typedef struct {
  int16_t sa[2];
  int16_t rec[NC];
  int32_t err;
} apath_t;

/* A's shape: the PATHS nearest vectors of stage 1, each with its nearest of stage 2 */
static int code_a(const slim_frame_t *f, apath_t *p) {
  int16_t s0[SLIM_MAXP], r[NC];
  int np = PATHS > SLIM_MAXP ? SLIM_MAXP : PATHS, i, k;
  np = cb_search(0, f->c, 1, 1, s0, np);
  for (i = 0; i < np; i++, p++) {
    memcpy(r, f->c, sizeof r);
    p->sa[0] = s0[i];
    cb_sub(0, s0[i], r, 1, 1);
    cb_search(1, r, 1, 1, &p->sa[1], 1);
    p->err = cb_sub(1, p->sa[1], r, 1, 1);
    for (k = 0; k < NC; k++) p->rec[k] = (int16_t)(f->c[k] - r[k]);
  }
  return np;
}

/* B's shape between A reconstructions ra and rn: its codeword of stage LR_BST, and its error */
static int32_t code_b(const slim_frame_t *b, const int16_t *ra, const int16_t *rn, int16_t *sb) {
  int16_t r[NC];
  int k;
  for (k = 0; k < NC; k++) r[k] = (int16_t)(b->c[k] - ((ra[k] + rn[k]) >> 1));
  cb_search(LR_BST, r, 3, 2, sb, 1);
  return cb_sub(LR_BST, *sb, r, 3, 2);
}

/* the superframe A, B with the next A frame's fields nx and B's shape codeword sb */
static void code_superframe(slim_enc_t *e, const slim_frame_t *nx, int sb, unsigned char *out) {
  const slim_frame_t *a = &e->fa, *b = &e->fb;
  int pos = 0, dw, de, wint, va = a->code != 0, vn = nx->code != 0;
  de = q_near(lr_e_tab, b->ei - ((a->ei + nx->ei + 1) >> 1));
  wint = va && vn ? (a->wi + nx->wi + 1) >> 1 : va ? a->wi : vn ? nx->wi : -1;
  if (b->code == 0) dw = LR_W_ZERO;
  else if (wint < 0) dw = q_near_u(lr_w_abs, b->wi);
  else dw = q_near(lr_w_tab, b->wi - wint);
  memset(out, 0, SLIM_BYTES);
  put_bits(out, &pos, a->code, 2);
  put_bits(out, &pos, a->wi, 7);
  put_bits(out, &pos, a->ei, 5);
  put_bits(out, &pos, e->sa[0], 9);
  put_bits(out, &pos, e->sa[1], 9);
  put_bits(out, &pos, b->code, 2);
  put_bits(out, &pos, dw, LR_WB_BITS);
  put_bits(out, &pos, de, LR_EB_BITS);
  put_bits(out, &pos, sb, 8);
}

/* An A frame closes the superframe before it: of its shape paths, the one with the least
   error over itself and the B frame before it (frames with no energy count a tenth) */
int slim_coder_push(slim_enc_t *e, const slim_frame_t *f, unsigned char out[SLIM_BYTES]) {
  apath_t p[SLIM_MAXP];
  int16_t sb, sbi;
  int np, i, best = 0;
  int32_t be = 0;
  if (e->nfr++ & 1) {
    e->fb = *f, e->have_b = 1;
    return 0;
  }
  np = code_a(f, p);
  sb = 0;
  for (i = 0; i < np; i++) {
    int32_t d = p[i].err * (f->ei > 0 ? 10 : 1);
    if (e->have_a) d += code_b(&e->fb, e->ra, p[i].rec, &sbi) * (e->fb.ei > 0 ? 10 : 1);
    if (i == 0 || d < be) be = d, best = i, sb = sbi;
  }
  if (e->have_a) code_superframe(e, f, sb, out);
  i = e->have_a;
  e->fa = *f, e->have_a = 1, e->have_b = 0;
  e->sa[0] = p[best].sa[0], e->sa[1] = p[best].sa[1];
  memcpy(e->ra, p[best].rec, sizeof e->ra);
  return i;
}

int slim_coder_flush(slim_enc_t *e, unsigned char out[SLIM_BYTES]) {
  int16_t sb;
  if (!e->have_a) return 0;
  if (!e->have_b) e->fb = e->fa;                             /* an odd count: B = A */
  code_b(&e->fb, e->ra, e->ra, &sb);                         /* the last superframe: next = itself */
  code_superframe(e, &e->fa, sb, out);
  e->have_a = 0;
  return 1;
}

int slim_encode10(slim_enc_t *e, const int16_t x[HOP], unsigned char out[SLIM_BYTES]) {
  slim_frame_t f;
  return slim_analyse10(e, x, &f) ? slim_coder_push(e, &f, out) : 0;
}

int slim_flush(slim_enc_t *e, unsigned char out[SLIM_BYTES]) {
  slim_frame_t f;
  while (slim_analyse_flush(e, &f))
    if (slim_coder_push(e, &f, out)) return 1;
  return slim_coder_flush(e, out);
}
