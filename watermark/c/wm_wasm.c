/* WebAssembly entry points for the watermark page (docs/watermark.html, docs/watermark.js).
 * Audio is 8 kHz float32 near -26 dBFS. Band 0 is the wide layout (500-2600 Hz, 4 bits per
 * slot), band 1 the narrow one (900-2000 Hz, 2 bits).
 * SPDX-License-Identifier: MIT */
#include "wm.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define EXPORT(name) __attribute__((export_name(#name)))

EXPORT(wm_alloc) void *wm_alloc(int n) { return malloc((size_t)n); }
EXPORT(wm_free) void wm_free(void *p) { free(p); }

static void band(int b, wm_params *p) {
  wm_default_params(p);
  if (b == 1) { p->lo = 900; p->hi = 2000; p->nsub = 2; }
}

static double *to_d(const float *x, int n) {
  double *d = malloc(sizeof(double) * (n > 0 ? n : 1));
  for (int i = 0; i < n; i++) d[i] = x[i];
  return d;
}

/* Mark x with the ID frame (call, code). y gets n samples; used and bits get, per slot
   (n / 256 of them), whether it was marked and the nsub bits it was given. Returns the slots. */
EXPORT(wm_js_mark) int wm_js_mark(const float *x, int n, const char *call, int code, int b, float *y,
                                  unsigned char *used, unsigned char *bits) {
  wm_params p;
  band(b, &p);
  wm_code c;
  wm_code_init(&c, call, code, p.nsub);
  double *xd = to_d(x, n), *yd = malloc(sizeof(double) * n), *f0 = malloc(sizeof(double) * n);
  unsigned char *v = malloc(n);
  wm_tx_track(xd, n, f0, v);
  int ns = wm_embed(&p, xd, n, f0, v, &c, yd, used);
  for (int i = 0; i < n; i++) y[i] = (float)yd[i];
  for (int j = 0; j < ns; j++) wm_bits_for_slot(&c, j, bits + j * p.nsub);
  free(xd); free(yd); free(f0); free(v);
  return ns;
}

/* fmchan.channel: kind 0 clean, 1 300-3000 Hz, 2 simplex, 3 repeater */
EXPORT(wm_js_channel) void wm_js_channel(const float *x, int n, int kind, double cnr_in, double cnr_out,
                                         double drive_db, int seed, float *y) {
  double *xd = to_d(x, n), *yd = malloc(sizeof(double) * n);
  wm_channel(xd, n, kind, cnr_in, cnr_out, drive_db, (unsigned)seed, yd);
  for (int i = 0; i < n; i++) y[i] = (float)yd[i];
  free(xd); free(yd);
}

/* The receiver as audio arrives: every `step` samples it reads all the audio heard so far
 * (timing, equaliser, polarity found again each time) and tries to decode the frame; an ID
 * counts as confirmed when the same frame and codeword start decode twice running, as
 * run.py's first_decode_s. Returns a block of doubles (free with wm_free):
 *   [0] header size H = 8, [1] nsub, [2] pitch frames P (10 ms), [3] checkpoints E,
 *   [4] slot records S, [5] seconds to the first confirmed ID or -1, [6] final grid offset,
 *   [7] slot records per checkpoint offset table (unused, 0)
 *   then P pitch values (Hz, 0 = unvoiced, the receiver's own track),
 *   then E checkpoints of 12 + WM_NCODE: t (s), offset, slots, cover, got, code, start,
 *        quality, confirmed, call (3 doubles: 2 characters each as c0 + 256 c1), ring[WM_NCODE]
 *        (soft sum per grid position mod WM_NCODE; signed against the decoded codeword when got)
 *   then S slot records of 2 + nsub: t0 (s), checkpoint index, soft value per sub-band
 *        (the slot as the receiver first read it, positive = 0) */
EXPORT(wm_js_receive) double *wm_js_receive(const float *x, int n, int b, int step) {
  wm_params p;
  band(b, &p);
  double *yd = to_d(x, n), *f0 = malloc(sizeof(double) * n);
  unsigned char *v = malloc(n);
  wm_pitch_track(yd, n, f0, v);
  wm_rx *rx = wm_rx_create(&p, yd, n, f0, v);
  int nsub = p.nsub, P = n / 80, E = 0, S = 0, ms = wm_rx_max_slots(rx);
  int ecap = n / step + 2, rw = 2 + nsub, ew = 12 + WM_NCODE;
  double *R = malloc(sizeof(double) * ms * nsub);
  double *ev = malloc(sizeof(double) * ecap * ew), *sr = malloc(sizeof(double) * ms * 4 * rw);
  int scap = ms * 4, prev_t = 0, pok = 0, final_off = 0;
  wm_frame prev = {{0}}, f;
  double first = -1;
  for (int t = step; ; t += step) {
    if (t > n) t = n;
    int off, m = wm_rx_read(rx, t, R, &off);
    double cover = 0, *e = ev + E * ew;
    int got = wm_decode(R, m, nsub, &f, &cover, e + 12);
    int conf = got && pok && !strcmp(f.call, prev.call) && f.code == prev.code && f.start == prev.start;
    if (conf && first < 0) first = (double)t / WM_FS;
    e[0] = (double)t / WM_FS; e[1] = off; e[2] = m; e[3] = cover; e[4] = got;
    e[5] = got ? f.code : 0; e[6] = got ? f.start : 0; e[7] = got ? f.quality : 0; e[8] = conf;
    for (int i = 0; i < 3; i++)
      e[9 + i] = got ? (unsigned char)f.call[2 * i] + 256.0 * (f.call[2 * i] ? (unsigned char)f.call[2 * i + 1] : 0) : 0;
    if (got) {   /* ring sign: positive where the soft sum agrees with the decoded codeword */
      wm_code c;
      wm_code_init(&c, f.call, f.code, nsub);
      for (int r2 = 0; r2 < WM_NCODE; r2++) e[12 + r2] *= 1 - 2 * c.cw[wm_perm((r2 + f.start) % WM_NCODE)];
    }
    for (int j = 0; j < m; j++) {
      int t1 = off + (j + 1) * WM_SLOT;
      if (t1 <= prev_t || S >= scap) continue;
      double *s = sr + S++ * rw;
      s[0] = (double)(off + j * WM_SLOT) / WM_FS;
      s[1] = E;
      for (int k = 0; k < nsub; k++) s[2 + k] = R[j * nsub + k];
    }
    E++;
    prev_t = t;
    pok = got;
    if (got) prev = f;
    final_off = off;
    if (t >= n) break;
  }
  int H = 8;
  double *out = malloc(sizeof(double) * (H + P + E * ew + S * rw));
  out[0] = H; out[1] = nsub; out[2] = P; out[3] = E; out[4] = S; out[5] = first; out[6] = final_off; out[7] = 0;
  for (int i = 0; i < P; i++) {
    int c = i * 80 + 40 < n ? i * 80 + 40 : n - 1;
    out[H + i] = v[c] ? f0[c] : 0;
  }
  memcpy(out + H + P, ev, sizeof(double) * E * ew);
  memcpy(out + H + P + E * ew, sr, sizeof(double) * S * rw);
  wm_rx_destroy(rx);
  free(yd); free(f0); free(v); free(R); free(ev); free(sr);
  return out;
}
