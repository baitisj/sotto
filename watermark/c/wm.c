/* Harmonic phase watermark: sender, receiver, ID frame and FM channel. See wm.h.
 * Follows watermark/harmonic.py, fec.py and fmchan.py step for step; check_c.py compares them.
 * SPDX-License-Identifier: MIT */
#include "wm.h"
#include "wm_tables.h"
#include <complex.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PI 3.14159265358979323846
#define FMIN 70.0
#define RAMP 64
#define SPAN (WM_SLOT / 2)
#define STEP 8
#define NOFF (2 * SPAN / STEP)
#define NBINS 12

typedef double complex cplx;

void wm_default_params(wm_params *p) {
  p->lo = 500.0;
  p->hi = 2600.0;
  p->nsub = 4;
  p->strength = 1.0;
}

/* ================================================================ filters (scipy) ==== */

/* sosfilt, direct form II transposed, state zi[2 * nsec] (updated) */
static void sosfilt_r(const double *sos, int nsec, double *x, int n, double *zi) {
  for (int s = 0; s < nsec; s++) {
    const double *c = sos + 6 * s;
    double b0 = c[0] / c[3], b1 = c[1] / c[3], b2 = c[2] / c[3], a1 = c[4] / c[3], a2 = c[5] / c[3];
    double z0 = zi ? zi[2 * s] : 0, z1 = zi ? zi[2 * s + 1] : 0;
    for (int i = 0; i < n; i++) {
      double xi = x[i], yi = b0 * xi + z0;
      z0 = b1 * xi - a1 * yi + z1;
      z1 = b2 * xi - a2 * yi;
      x[i] = yi;
    }
    if (zi) { zi[2 * s] = z0; zi[2 * s + 1] = z1; }
  }
}

static void sosfilt_c(const double *sos, int nsec, cplx *x, int n, const cplx *zi) {
  for (int s = 0; s < nsec; s++) {
    const double *c = sos + 6 * s;
    double b0 = c[0] / c[3], b1 = c[1] / c[3], b2 = c[2] / c[3], a1 = c[4] / c[3], a2 = c[5] / c[3];
    cplx z0 = zi ? zi[2 * s] : 0, z1 = zi ? zi[2 * s + 1] : 0;
    for (int i = 0; i < n; i++) {
      cplx xi = x[i], yi = b0 * xi + z0;
      z0 = b1 * xi - a1 * yi + z1;
      z1 = b2 * xi - a2 * yi;
      x[i] = yi;
    }
  }
}

/* sosfilt_zi: steady state of each section for a unit step, scaled by the gain before it */
static void sos_zi(const double *sos, int nsec, double *zi) {
  double scale = 1.0;
  for (int s = 0; s < nsec; s++) {
    const double *c = sos + 6 * s;
    double b0 = c[0] / c[3], b1 = c[1] / c[3], b2 = c[2] / c[3], a1 = c[4] / c[3], a2 = c[5] / c[3];
    double g = (b0 + b1 + b2) / (1 + a1 + a2);
    zi[2 * s] = scale * (g - b0);
    zi[2 * s + 1] = scale * (b2 - a2 * g);
    scale *= g;
  }
}

/* sosfiltfilt with scipy's default odd padding, in place (complex) */
static void sosfiltfilt_c(const double *sos, int nsec, cplx *x, int n) {
  int nb = 0, na = 0;
  for (int s = 0; s < nsec; s++) { nb += sos[6 * s + 2] == 0; na += sos[6 * s + 5] == 0; }
  int pad = 3 * (2 * nsec + 1 - (nb < na ? nb : na));
  if (n <= pad) pad = n - 1;
  if (pad < 0) return;
  int m = n + 2 * pad;
  cplx *e = malloc(sizeof(cplx) * m);
  double zr[16];
  cplx zi[16];
  for (int i = 0; i < pad; i++) e[i] = 2 * x[0] - x[pad - i];
  memcpy(e + pad, x, sizeof(cplx) * n);
  for (int i = 0; i < pad; i++) e[pad + n + i] = 2 * x[n - 1] - x[n - 2 - i];
  sos_zi(sos, nsec, zr);
  for (int s = 0; s < 2 * nsec; s++) zi[s] = zr[s] * e[0];
  sosfilt_c(sos, nsec, e, m, zi);
  for (int i = 0; i < m / 2; i++) { cplx t = e[i]; e[i] = e[m - 1 - i]; e[m - 1 - i] = t; }
  for (int s = 0; s < 2 * nsec; s++) zi[s] = zr[s] * e[0];
  sosfilt_c(sos, nsec, e, m, zi);
  for (int i = 0; i < n; i++) x[i] = e[m - 1 - pad - i];
  free(e);
}

/* ============================================================ message (fec.py) ==== */

static const char ALPHABET[] = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/.";
#define G1 0171
#define G2 0133
#define KC 7
#define NSTATE 64

static int parity(unsigned v) {
  int p = 0;
  while (v) { p ^= v & 1; v >>= 1; }
  return p;
}
static int next_state(int s, int u) { return ((u << (KC - 1)) | s) >> 1; }
static int out_bit(int s, int u, int g) { return parity(((u << (KC - 1)) | s) & g); }

static unsigned crc16(const unsigned char *b, int n) {
  unsigned r = 0xFFFF;
  for (int i = 0; i < n; i++) {
    int top = (r >> 15) & 1;
    r = (r << 1) & 0xFFFF;
    if (top ^ b[i]) r ^= 0x1021;
  }
  return r;
}

static void put(unsigned char *b, unsigned long v, int n) {
  for (int i = 0; i < n; i++) b[i] = (v >> (n - 1 - i)) & 1;
}
static unsigned long val(const unsigned char *b, int n) {
  unsigned long v = 0;
  for (int i = 0; i < n; i++) v = (v << 1) | b[i];
  return v;
}

static void conv_encode(const unsigned char *bits, unsigned char *out) {
  int s = 0, o = 0;
  for (int i = 0; i < WM_MSGBITS + KC - 1; i++) {
    int u = i < WM_MSGBITS ? bits[i] : 0;
    out[o++] = out_bit(s, u, G1);
    out[o++] = out_bit(s, u, G2);
    s = next_state(s, u);
  }
}

int wm_perm(int q) { return (q * WM_STRIDE) % WM_NCODE; }
static int perm(int q) { return wm_perm(q); }

void wm_code_init(wm_code *c, const char *call, int code, int nsub) {
  unsigned long v = 0;
  int len = 0;
  while (call[len] && len < 6) len++;
  for (int i = len - 1; i >= 0; i--) {
    int ch = call[i];
    if (ch >= 'a' && ch <= 'z') ch -= 32;
    const char *p = strchr(ALPHABET, ch);
    v = v * 40 + (p && ch ? (unsigned long)(p - ALPHABET) : 0);
  }
  put(c->msg, v, 32);
  put(c->msg + 32, code & 0xFF, 8);
  put(c->msg + 40, crc16(c->msg, 40), 16);
  conv_encode(c->msg, c->cw);
  for (int i = 0; i < WM_NCODE; i++) c->cw[i] ^= wm_pn[i];
  c->nsub = nsub;
}

void wm_bits_for_slot(const wm_code *c, int j, unsigned char *bits) {
  for (int b = 0; b < c->nsub; b++) bits[b] = c->cw[perm((j * c->nsub + b) % WM_NCODE)];
}

/* soft Viterbi (fec.viterbi): soft[2 * t + i] positive = 0, 0 = erased; ties keep the first
   predecessor, as numpy's argmax */
static void viterbi(const double *soft, unsigned char *out) {
  enum { T = WM_NCODE / 2 };
  static int ps[NSTATE][2], pu[NSTATE][2], sg[NSTATE][2][2], ready;
  if (!ready) {
    int fill[NSTATE] = {0};
    for (int s = 0; s < NSTATE; s++)
      for (int u = 0; u < 2; u++) {
        int nx = next_state(s, u);
        ps[nx][fill[nx]] = s;
        pu[nx][fill[nx]] = u;
        sg[nx][fill[nx]][0] = 1 - 2 * out_bit(s, u, G1);
        sg[nx][fill[nx]][1] = 1 - 2 * out_bit(s, u, G2);
        fill[nx]++;
      }
    ready = 1;
  }
  double pm[NSTATE], nm[NSTATE];
  static unsigned char hist[T][NSTATE];
  for (int s = 0; s < NSTATE; s++) pm[s] = -1e18;
  pm[0] = 0;
  for (int t = 0; t < T; t++) {
    double s0 = soft[2 * t], s1 = soft[2 * t + 1];
    for (int s = 0; s < NSTATE; s++) {
      double c0 = pm[ps[s][0]] + (sg[s][0][0] * s0 + sg[s][0][1] * s1);
      double c1 = pm[ps[s][1]] + (sg[s][1][0] * s0 + sg[s][1][1] * s1);
      int c = c1 > c0;
      hist[t][s] = c;
      nm[s] = c ? c1 : c0;
    }
    memcpy(pm, nm, sizeof pm);
  }
  unsigned char rev[T];
  int s = 0;
  for (int t = T - 1; t >= 0; t--) {
    int i = hist[t][s];
    rev[t] = pu[s][i];
    s = ps[s][i];
  }
  memcpy(out, rev, WM_MSGBITS);
}

int wm_decode(const double *R, int nslots, int nsub, wm_frame *f, double *cover, double *ring) {
  double G[WM_NCODE] = {0};
  int total = nslots * nsub;
  for (int i = 0; i < total; i++) G[i % WM_NCODE] += R[i];
  int heard = 0;
  for (int r = 0; r < WM_NCODE; r++) heard += G[r] != 0;
  if (ring) memcpy(ring, G, sizeof G);
  if (cover) *cover = (double)heard / WM_NCODE;
  if (heard < 0.8 * WM_NCODE) return 0;
  for (int st = 0; st < WM_NCODE; st++) {
    double acc[WM_NCODE];
    for (int r = 0; r < WM_NCODE; r++) {
      int k = perm((r + st) % WM_NCODE);
      acc[k] = G[r] * (1 - 2 * wm_pn[k]);
    }
    unsigned char bits[WM_MSGBITS], cw[WM_NCODE];
    viterbi(acc, bits);
    if (crc16(bits, 40) != val(bits + 40, 16)) continue;
    conv_encode(bits, cw);
    double num = 0, den = 1e-30;
    for (int i = 0; i < WM_NCODE; i++) { num += acc[i] * (1 - 2 * cw[i]); den += fabs(acc[i]); }
    double q = num / den;
    if (q < 0.9) continue;
    unsigned long v = val(bits, 32);
    int len = 0;
    while (v && len < 7) { f->call[len++] = ALPHABET[v % 40]; v /= 40; }
    f->call[len] = 0;
    f->code = (int)val(bits + 32, 8);
    f->start = st;
    f->quality = q;
    return 1;
  }
  return 0;
}

/* ========================================================= harmonics (harmonic.py) ==== */

typedef struct { int c0, c1, voiced; double f; } slot_t;

static int cmp_d(const void *a, const void *b) {
  double x = *(const double *)a, y = *(const double *)b;
  return (x > y) - (x < y);
}

/* harmonic._slot_layout with gate "all" */
static int layout(int n, const double *f0, const unsigned char *v, int offset, slot_t *out) {
  int ns = (n - (offset > 0 ? offset : 0)) / WM_SLOT;
  double *tmp = malloc(sizeof(double) * WM_SLOT);
  for (int j = 0; j < ns; j++) {
    int a = j * WM_SLOT + offset, b = a + WM_SLOT;
    if (a < 0) { out[j].c0 = out[j].c1 = 0; out[j].f = FMIN; out[j].voiced = 0; continue; }
    int all = 1;
    for (int i = a; i < b; i++) { all &= v[i] != 0; tmp[i - a] = f0[i]; }
    qsort(tmp, WM_SLOT, sizeof(double), cmp_d);
    double med = 0.5 * (tmp[WM_SLOT / 2 - 1] + tmp[WM_SLOT / 2]);
    out[j].c0 = a + WM_SLOT / 4;
    out[j].c1 = b - WM_SLOT / 4;
    out[j].f = med > FMIN ? med : FMIN;
    out[j].voiced = all;
  }
  free(tmp);
  return ns;
}

/* sub-band of harmonic k at pitch f, or -1 when k f is outside the band (_odd_in_band) */
static int subband(const wm_params *p, int k, double f) {
  double kf = k * f;
  if (kf < p->lo || kf > p->hi) return -1;
  int b = 0;
  double r = log(p->hi / p->lo);
  for (int i = 1; i <= p->nsub; i++) {
    double e = i == p->nsub ? p->hi : p->lo * exp(r * i / p->nsub);
    if (kf >= e) b = i;
  }
  return b < p->nsub - 1 ? b : p->nsub - 1;
}

static int kmax_of(const wm_params *p) { return (int)(p->hi / FMIN) + 2; }

/* rolling harmonic rows: Z[k] = sosfiltfilt(lpf, x e^{-j k phi}) for k = 1, 2, ... */
typedef struct {
  int n, k;
  cplx *base, *pw, *row[3];   /* row[i] = Z[k - 2 + i] */
  const double *x;
} hrows;

static void hrows_init(hrows *h, const double *x, int n, const double *f0) {
  h->n = n;
  h->x = x;
  h->base = malloc(sizeof(cplx) * n);
  h->pw = malloc(sizeof(cplx) * n);
  for (int i = 0; i < 3; i++) h->row[i] = malloc(sizeof(cplx) * n);
  double phi = 0;
  for (int i = 0; i < n; i++) {
    phi += 2 * PI * f0[i] / WM_FS;
    h->base[i] = cexp(-I * fmod(phi, 2 * PI));
    h->pw[i] = 1;
  }
  h->k = 0;
}

/* advance to row k + 1 (rows shift down) */
static void hrows_next(hrows *h) {
  cplx *t = h->row[0];
  h->row[0] = h->row[1];
  h->row[1] = h->row[2];
  h->row[2] = t;
  h->k++;
  for (int i = 0; i < h->n; i++) {
    h->pw[i] *= h->base[i];
    t[i] = h->x[i] * h->pw[i];
  }
  sosfiltfilt_c(sos_lpf, SOS_LPF_N, t, h->n);
}

static void hrows_free(hrows *h) {
  free(h->base);
  free(h->pw);
  for (int i = 0; i < 3; i++) free(h->row[i]);
}

/* harmonic._triplet over [c0, c1) for zm = Z[k-1], z0 = Z[k], zp = Z[k+1] */
static cplx triplet(const cplx *zm, const cplx *z0, const cplx *zp, int c0, int c1, double *nn,
                    double *amp) {
  cplx r = 0;
  double n = 0, a = 0;
  for (int i = c0; i < c1; i++) {
    double am = cabs(zm[i]), a0 = cabs(z0[i]), ap = cabs(zp[i]);
    cplx c = conj(z0[i]);
    r += zp[i] * zm[i] * c * c;
    n += ap * am * a0 * a0;
    double lo = ap < am ? ap : am;
    a += lo < a0 ? lo : a0;
  }
  *nn = n + 1e-30;
  *amp = a / (c1 - c0);
  return r;
}

int wm_embed(const wm_params *p, const double *x, int n, const double *f0, const unsigned char *v,
             const wm_code *c, double *y, unsigned char *used) {
  int kmax = kmax_of(p), ns = n / WM_SLOT;
  slot_t *lay = malloc(sizeof(slot_t) * (ns + 1));
  layout(n, f0, v, 0, lay);
  double w[RAMP], ws = 0, *delta = malloc(sizeof(double) * n);
  for (int i = 0; i < RAMP; i++) { w[i] = 0.5 - 0.5 * cos(2 * PI * (i + 1) / (RAMP + 1)); ws += w[i]; }
  for (int i = 0; i < RAMP; i++) w[i] /= ws;
  memcpy(y, x, sizeof(double) * n);
  memset(used, 0, ns);
  unsigned char (*bits)[WM_MAXSUB] = malloc(sizeof(*bits) * (ns + 1)), *used_k = malloc(ns + 1);
  for (int j = 0; j < ns; j++) wm_bits_for_slot(c, j, bits[j]);
  hrows h;
  hrows_init(&h, x, n, f0);
  hrows_next(&h);                 /* row[2] = Z1 */
  hrows_next(&h);                 /* Z1, Z2 */
  double *phi = malloc(sizeof(double) * n), ph = 0;
  for (int i = 0; i < n; i++) { ph += 2 * PI * f0[i] / WM_FS; phi[i] = ph; }
  for (int k = 3; k < kmax + 2; k += 2) {
    hrows_next(&h);               /* rows Z[k-2], Z[k-1], Z[k] */
    hrows_next(&h);               /* rows Z[k-1], Z[k], Z[k+1] */
    cplx *zm = h.row[0], *z0 = h.row[1], *zp = h.row[2];
    int any = 0;
    memset(delta, 0, sizeof(double) * n);
    memset(used_k, 0, ns + 1);
    for (int j = 0; j < ns; j++) {
      if (!lay[j].voiced) continue;
      int sb = subband(p, k, lay[j].f);
      if (sb < 0) continue;
      double nn, amp;
      cplx r = triplet(zm, z0, zp, lay[j].c0, lay[j].c1, &nn, &amp);
      double th = PI * bits[j][sb];
      double d = carg(r) - th;
      double dl = carg(cexp(I * d)) / 2;
      for (int i = j * WM_SLOT; i < (j + 1) * WM_SLOT; i++) delta[i] = p->strength * dl;
      used[j] = used_k[j] = 1;
      any = 1;
    }
    if (any) {
      /* np.convolve(delta, w, "same"): output i = sum_m delta[i + 31 - m] w[m] */
      for (int i = 0; i < n; i++) {
        int s0 = (i - RAMP / 2) / WM_SLOT, s1 = (i + RAMP / 2) / WM_SLOT;
        if (i >= RAMP / 2 && s1 < ns && !used_k[s0] && !used_k[s1]) continue;
        double dk = 0;
        for (int m = 0; m < RAMP; m++) {
          int q = i + (RAMP - 1) / 2 - m;
          if (q >= 0 && q < n) dk += delta[q] * w[m];
        }
        if (dk != 0) y[i] += 2 * creal(z0[i] * (cexp(I * dk) - 1) * cexp(I * fmod(k * phi[i], 2 * PI)));
      }
    }
  }
  hrows_free(&h);
  free(phi);
  free(bits);
  free(used_k);
  free(delta);
  free(lay);
  return ns;
}

/* ------------------------------------------------------------------ receiver ---- */

typedef struct { int j, sb; double f; cplx u; } rec_t;

struct wm_rx {
  wm_params p;
  int n, ns[NOFF], nrec[NOFF];
  slot_t *lay[NOFF];
  rec_t *rec[NOFF];
};

int wm_rx_max_slots(const wm_rx *r) { return r->n / WM_SLOT + 1; }

wm_rx *wm_rx_create(const wm_params *p, const double *y, int n, const double *f0,
                    const unsigned char *v) {
  wm_rx *r = calloc(1, sizeof *r);
  r->p = *p;
  r->n = n;
  int cap[NOFF];
  for (int o = 0; o < NOFF; o++) {
    r->lay[o] = malloc(sizeof(slot_t) * (n / WM_SLOT + 1));
    r->ns[o] = layout(n, f0, v, -SPAN + o * STEP, r->lay[o]);
    cap[o] = 64;
    r->rec[o] = malloc(sizeof(rec_t) * cap[o]);
  }
  int kmax = kmax_of(p);
  hrows h;
  hrows_init(&h, y, n, f0);
  hrows_next(&h);
  hrows_next(&h);
  for (int k = 3; k < kmax + 2; k += 2) {
    hrows_next(&h);
    hrows_next(&h);
    cplx *zm = h.row[0], *z0 = h.row[1], *zp = h.row[2];
    for (int o = 0; o < NOFF; o++)
      for (int j = 0; j < r->ns[o]; j++) {
        slot_t *s = &r->lay[o][j];
        if (!s->voiced) continue;
        int sb = subband(p, k, s->f);
        if (sb < 0) continue;
        double nn, amp;
        cplx t = triplet(zm, z0, zp, s->c0, s->c1, &nn, &amp);
        if (r->nrec[o] == cap[o]) r->rec[o] = realloc(r->rec[o], sizeof(rec_t) * (cap[o] *= 2));
        r->rec[o][r->nrec[o]++] = (rec_t){j, sb, k * s->f, amp * t / nn};
      }
  }
  hrows_free(&h);
  return r;
}

void wm_rx_destroy(wm_rx *r) {
  if (!r) return;
  for (int o = 0; o < NOFF; o++) { free(r->lay[o]); free(r->rec[o]); }
  free(r);
}

/* slots of offset o that end by sample upto */
static int slots_upto(const wm_rx *r, int o, int upto) {
  int off = -SPAN + o * STEP, m = (upto - off) / WM_SLOT;
  if (m > r->ns[o]) m = r->ns[o];
  return m < 0 ? 0 : m;
}

static int eq_bin(double f, const double *edges, int nb) {
  int i = 0;                       /* np.searchsorted(edges, f) - 1, clipped */
  while (i < nb + 1 && edges[i] < f) i++;
  i -= 1;
  return i < 0 ? 0 : i >= nb ? nb - 1 : i;
}

/* np.unwrap: corrections from the original differences, accumulated */
static void unwrap(double *a, int n) {
  double corr = 0, prev = a[0];
  for (int i = 1; i < n; i++) {
    double d = a[i] - prev, dd = fmod(d + PI, 2 * PI);
    if (dd < 0) dd += 2 * PI;
    dd -= PI;
    if (dd == -PI && d > 0) dd = PI;
    if (fabs(d) >= PI) corr += dd - d;
    prev = a[i];
    a[i] += corr;
  }
}

int wm_rx_read(wm_rx *r, int upto, double *R, int *offset) {
  int nsub = r->p.nsub;
  /* find_offset: |sum S^2| / sum |S|^2 over sub-bands */
  int best = -1, bm = 0;
  double bv = 0;
  cplx *S = calloc((size_t)(r->n / WM_SLOT + 1) * nsub, sizeof(cplx));
  for (int o = 0; o < NOFF; o++) {
    int m = slots_upto(r, o, upto);
    memset(S, 0, sizeof(cplx) * (r->n / WM_SLOT + 1) * nsub);
    for (int i = 0; i < r->nrec[o]; i++) {
      rec_t *e = &r->rec[o][i];
      if (e->j < m) S[e->j * nsub + e->sb] += e->u;
    }
    double num = 0, den = 1e-30;
    for (int b = 0; b < nsub; b++) {
      cplx s2 = 0;
      for (int j = 0; j < m; j++) {
        cplx s = S[j * nsub + b];
        s2 += s * s;
        den += creal(s) * creal(s) + cimag(s) * cimag(s);
      }
      num += cabs(s2);
    }
    double metric = num / den;
    if (best < 0 || metric > bv) { best = o; bv = metric; bm = m; }
  }
  /* equalizer: per frequency bin, half the angle of the summed squared phasors */
  double edges[NBINS + 1], two[NBINS];
  cplx acc[NBINS] = {0};
  double lr = log(r->p.hi / r->p.lo);
  for (int i = 0; i <= NBINS; i++) edges[i] = r->p.lo * exp(lr * i / NBINS);
  edges[0] = r->p.lo;
  edges[NBINS] = r->p.hi;
  rec_t *rec = r->rec[best];
  for (int i = 0; i < r->nrec[best]; i++)
    if (rec[i].j < bm) acc[eq_bin(rec[i].f, edges, NBINS)] += rec[i].u * rec[i].u;
  for (int i = 0; i < NBINS; i++) two[i] = carg(acc[i]);
  int mid = NBINS / 2;
  unwrap(two + mid, NBINS - mid);
  double rv[NBINS];
  for (int i = 0; i <= mid; i++) rv[i] = two[mid - i];
  unwrap(rv, mid + 1);
  for (int i = 0; i <= mid; i++) two[mid - i] = rv[i];
  memset(S, 0, sizeof(cplx) * (r->n / WM_SLOT + 1) * nsub);
  for (int i = 0; i < r->nrec[best]; i++)
    if (rec[i].j < bm)
      S[rec[i].j * nsub + rec[i].sb] += rec[i].u * cexp(-I * two[eq_bin(rec[i].f, edges, NBINS)] / 2);
  /* derotate each sub-band by half the angle of sum S^2 */
  for (int b = 0; b < nsub; b++) {
    cplx s2 = 0;
    for (int j = 0; j < bm; j++) s2 += S[j * nsub + b] * S[j * nsub + b];
    cplx rot = cexp(-I * carg(s2) / 2);
    for (int j = 0; j < bm; j++) R[j * nsub + b] = creal(S[j * nsub + b] * rot);
  }
  free(S);
  if (offset) *offset = -SPAN + best * STEP;
  return bm;
}

/* ============================================================== channel (fmchan.py) ==== */

#define FS_RF 48000
#define DEV 2500.0

static void lfilter1(const double *c, double *x, int n) {
  double b0 = c[0] / c[2], b1 = c[1] / c[2], a1 = c[3] / c[2], xp = 0, yp = 0;
  for (int i = 0; i < n; i++) {
    double yi = b0 * x[i] + b1 * xp - a1 * yp;
    xp = x[i];
    yp = yi;
    x[i] = yi;
  }
}

static double percentile_abs(const double *x, int n, double q) {
  double *a = malloc(sizeof(double) * n);
  for (int i = 0; i < n; i++) a[i] = fabs(x[i]);
  qsort(a, n, sizeof(double), cmp_d);
  double idx = q / 100 * (n - 1);
  int lo = (int)floor(idx);
  double fr = idx - lo, v = lo + 1 < n ? a[lo] + fr * (a[lo + 1] - a[lo]) : a[lo];
  free(a);
  return v;
}

static void tx_audio(const double *x, int n, double drive_db, double *y) {
  memcpy(y, x, sizeof(double) * n);
  lfilter1(emph_pre, y, n);
  double ref = percentile_abs(y, n, 99.5) + 1e-9, g = pow(10, drive_db / 20) / ref;
  for (int i = 0; i < n; i++) {
    double v = y[i] * g;
    y[i] = v > 1 ? 1 : v < -1 ? -1 : v;
  }
  sosfilt_r(sos_tx_lp, SOS_TX_LP_N, y, n, NULL);
  sosfilt_r(sos_tx_hp, SOS_TX_HP_N, y, n, NULL);
}

/* xoshiro128** and Box-Muller */
typedef struct { unsigned s[4]; int have; double spare; } rng_t;
static unsigned rotl(unsigned x, int k) { return (x << k) | (x >> (32 - k)); }
static unsigned rng_u32(rng_t *r) {
  unsigned res = rotl(r->s[1] * 5, 7) * 9, t = r->s[1] << 9;
  r->s[2] ^= r->s[0]; r->s[3] ^= r->s[1]; r->s[1] ^= r->s[2]; r->s[0] ^= r->s[3];
  r->s[2] ^= t; r->s[3] = rotl(r->s[3], 11);
  return res;
}
static void rng_seed(rng_t *r, unsigned seed) {
  unsigned z = seed * 2654435761u + 0x9E3779B9u;
  for (int i = 0; i < 4; i++) { z ^= z >> 16; z *= 0x85EBCA6Bu; z ^= z >> 13; z *= 0xC2B2AE35u; z ^= z >> 16; r->s[i] = z + i; }
  r->have = 0;
}
static double rng_normal(rng_t *r) {
  if (r->have) { r->have = 0; return r->spare; }
  double u1 = (rng_u32(r) + 1.0) / 4294967297.0, u2 = rng_u32(r) / 4294967296.0;
  double m = sqrt(-2 * log(u1));
  r->spare = m * sin(2 * PI * u2);
  r->have = 1;
  return m * cos(2 * PI * u2);
}

static void fm_hop(const double *m, int n, double cnr_db, int noisy, rng_t *rng, double *out) {
  int up = RS_RATE, N = n * up, L = 2 * RS_HALF + 1;
  /* resample_poly(m, 6, 1): zero-stuff, filter (gain 6), centred */
  double *mu = malloc(sizeof(double) * N);
  for (int i = 0; i < N; i++) {
    double s = 0;
    int t0 = i + RS_HALF;               /* full convolution index */
    for (int q = (t0 - (L - 1) + up - 1) / up; q <= t0 / up; q++) {
      if (q < 0 || q >= n) continue;
      s += m[q] * rs_fir[t0 - q * up];
    }
    mu[i] = s * up;
  }
  cplx *s = malloc(sizeof(cplx) * N);
  double ph = 0, npow = pow(10, -cnr_db / 10) * FS_RF / 12500.0, sd = sqrt(npow / 2);
  for (int i = 0; i < N; i++) {
    double dev = mu[i] * DEV + 0.12 * DEV * sin(2 * PI * 100.0 * i / FS_RF);
    ph += 2 * PI * dev / FS_RF;
    s[i] = cexp(I * fmod(ph, 2 * PI));
    if (noisy) {
      double a = rng_normal(rng), b = rng_normal(rng);
      s[i] += sd * (a + I * b);
    }
  }
  sosfiltfilt_c(sos_if, SOS_IF_N, s, N);
  double *d = mu;
  d[0] = 0;
  for (int i = 1; i < N; i++) d[i] = carg(s[i] * conj(s[i - 1])) * FS_RF / (2 * PI) / DEV;
  free(s);
  /* resample_poly(d, 1, 6)[:n]: y[k] = sum_j d[j] h[6k + 60 - j] */
  for (int k = 0; k < n; k++) {
    double acc = 0;
    int t0 = up * k + RS_HALF;
    for (int j = t0 - (L - 1); j <= t0; j++) {
      if (j < 0 || j >= N) continue;
      acc += d[j] * rs_fir[t0 - j];
    }
    out[k] = acc;
  }
  free(mu);
  lfilter1(emph_de, out, n);
  sosfilt_r(sos_voice, SOS_VOICE_N, out, n, NULL);
}

static double rms(const double *x, int n) {
  double s = 0;
  for (int i = 0; i < n; i++) s += x[i] * x[i];
  return sqrt(s / (n > 0 ? n : 1));
}

void wm_channel(const double *x, int n, int kind, double cnr_in, double cnr_out, double drive_db,
                unsigned seed, double *y) {
  if (kind == WM_CH_CLEAN) { memcpy(y, x, sizeof(double) * n); return; }
  if (kind == WM_CH_BANDPASS) {
    memcpy(y, x, sizeof(double) * n);
    sosfilt_r(sos_voice, SOS_VOICE_N, y, n, NULL);
    return;
  }
  rng_t rng;
  rng_seed(&rng, seed);
  double lvl = rms(x, n) + 1e-12, *m = malloc(sizeof(double) * n);
  tx_audio(x, n, drive_db, m);
  fm_hop(m, n, cnr_in, 1, &rng, y);
  if (kind == WM_CH_REPEATER) {
    tx_audio(y, n, 0.0, m);
    fm_hop(m, n, cnr_out, 1, &rng, y);
  }
  double g = lvl / (rms(y, n) + 1e-12);
  for (int i = 0; i < n; i++) y[i] *= g;
  free(m);
}
