/* Pitch tracks for the watermark from sotto's encoder pitch tracker (c/sotto.c: Codec 2's NLP
 * candidates, the fixed-lag Viterbi tracker, sub-octave folding and the voicing rules), one
 * decision per 10 ms analysis frame, spread to every sample as harmonic.pitch_track does.
 * SPDX-License-Identifier: MIT */
#include "wm.h"
#include "wm_tables.h"
#include "sotto_internal.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define NSAMP 80

/* per-frame Wo (Hz) and voicing, frame t centred on sample 80 t - 80 */
static int frames(const double *x, int n, double *f0, unsigned char *v) {
  int nf = n / NSAMP, got = 0;
  struct sotto_enc *e = sotto_enc_create();
  short blk[NSAMP];
  sotto_enc_frame_t fr;
  for (int t = 0; t <= nf; t++) {
    if (t < nf) {
      for (int i = 0; i < NSAMP; i++) {
        double s = round(x[t * NSAMP + i] * 32767);
        blk[i] = s > 32767 ? 32767 : s < -32768 ? -32768 : (short)s;
      }
      sotto_enc_analyse_block(e, blk);
    } else {
      sotto_enc_flush_core(e);
    }
    while (sotto_enc_pop_frame(e, &fr))
      for (int h = 0; h < 2; h++)
        if (got < nf) {
          f0[got] = exp(fr.lwo[h]) * WM_FS / (2 * 3.14159265358979323846);
          v[got] = !isnan(fr.snr[h]);
          got++;
        }
  }
  sotto_enc_destroy(e);
  return got;
}

/* np.interp(t, xp, fp) for increasing xp */
static void interp(int n, const double *xp, const double *fp, int m, double *out) {
  int j = 0;
  for (int t = 0; t < n; t++) {
    if (t <= xp[0]) { out[t] = fp[0]; continue; }
    if (t >= xp[m - 1]) { out[t] = fp[m - 1]; continue; }
    while (xp[j + 1] < t) j++;
    double a = (t - xp[j]) / (xp[j + 1] - xp[j]);
    out[t] = fp[j] + a * (fp[j + 1] - fp[j]);
  }
}

void wm_pitch_track(const double *x, int n, double *f0, unsigned char *v) {
  int nf = n / NSAMP;
  double *wf = malloc(sizeof(double) * (nf + 1)), *tc = malloc(sizeof(double) * (nf + 1));
  double *vf = malloc(sizeof(double) * (nf + 1)), *tv = malloc(sizeof(double) * (nf + 1));
  double *fv = malloc(sizeof(double) * (nf + 1)), *tmp = malloc(sizeof(double) * n);
  unsigned char *vv = malloc(nf + 1);
  int got = frames(x, n, wf, vv), nv = 0;
  for (int t = 0; t < got; t++) {
    tc[t] = 80.0 * t - 80;
    vf[t] = vv[t];
    if (vv[t]) { tv[nv] = tc[t]; fv[nv++] = wf[t]; }
  }
  if (nv < 2 || got < 2) {
    for (int i = 0; i < n; i++) { f0[i] = 120.0; v[i] = 0; }
  } else {
    interp(n, tv, fv, nv, f0);
    interp(n, tc, vf, got, tmp);
    for (int i = 0; i < n; i++) v[i] = tmp[i] > 0.5;
  }
  free(wf); free(tc); free(vf); free(tv); free(fv); free(tmp); free(vv);
}

void wm_tx_track(const double *x, int n, double *f0, unsigned char *v) {
  double *ff = malloc(sizeof(double) * n), *bp = malloc(sizeof(double) * n);
  unsigned char *vf = malloc(n), *vb = malloc(n);
  wm_pitch_track(x, n, ff, vf);
  memcpy(bp, x, sizeof(double) * n);
  /* the receiver's 300-3000 Hz filter (sosfilt, zero state) */
  for (int s = 0; s < SOS_VOICE_N; s++) {
    const double *c = sos_voice + 6 * s;
    double z0 = 0, z1 = 0;
    for (int i = 0; i < n; i++) {
      double xi = bp[i], yi = c[0] * xi + z0;
      z0 = c[1] * xi - c[4] * yi + z1;
      z1 = c[2] * xi - c[5] * yi;
      bp[i] = yi;
    }
  }
  wm_pitch_track(bp, n, f0, vb);
  for (int i = 0; i < n; i++) v[i] = vf[i] && vb[i] && fabs(log(f0[i] / ff[i])) < 0.05;
  free(ff); free(bp); free(vf); free(vb);
}
