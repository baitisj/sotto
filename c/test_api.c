/* API test against the shared library: a voiced, rising tone at the target level goes
 * through encoder and decoder, checking frame counts, delay and output level.
 * SPDX-License-Identifier: MIT */
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "sotto.h"

#define SECONDS 2
#define PI 3.14159265358979323846
#define N (SOTTO_SAMPLE_RATE * SECONDS / SOTTO_SAMPLES_PER_FRAME)

static double rms_dbfs(const short *x, int n) {
  double s = 0;
  for (int i = 0; i < n; i++) s += (double)x[i] * x[i];
  return 10 * log10(s / n / (32768.0 * 32768.0) + 1e-20);
}

int main(void) {
  static short in[N * SOTTO_SAMPLES_PER_FRAME], out[(N + 1) * SOTTO_SAMPLES_PER_FRAME];
  static unsigned char bits[N + 8][SOTTO_BYTES_PER_FRAME];
  /* buzz at 120-160 Hz: harmonics up to 3.5 kHz with falling amplitude */
  double ph = 0, amp = 0;
  for (int k = 1; k * 120 < 3500; k++) amp += 1.0 / (k * k);
  amp = 32768 * pow(10, SOTTO_LEVEL_TARGET_DBFS / 20) / sqrt(amp / 2);
  for (int i = 0; i < N * SOTTO_SAMPLES_PER_FRAME; i++) {
    double f0 = 120 + 40.0 * i / (N * SOTTO_SAMPLES_PER_FRAME), v = 0;
    ph += 2 * PI * f0 / SOTTO_SAMPLE_RATE;
    for (int k = 1; k * f0 < 3500; k++) v += sin(k * ph) / k;
    in[i] = (short)(amp * v);
  }
  printf("format: %s\n", sotto_format());
  struct sotto_enc *e = sotto_enc_create();
  int nf = 0;
  for (int f = 0; f < N; f++) nf += sotto_encode(e, in + f * SOTTO_SAMPLES_PER_FRAME, bits[nf]);
  int early = nf;
  while (sotto_enc_flush(e, bits[nf])) nf++;
  sotto_enc_destroy(e);
  struct sotto_dec *d = sotto_dec_create();
  for (int f = 0; f < nf; f++) sotto_decode(d, bits[f], 1, out + f * SOTTO_SAMPLES_PER_FRAME);
  sotto_dec_flush(d, out + nf * SOTTO_SAMPLES_PER_FRAME);
  sotto_dec_destroy(d);
  /* skip the decoder's 20 ms delay and the first and last 200 ms */
  int skip = SOTTO_SAMPLES_PER_FRAME + 1600, len = N * SOTTO_SAMPLES_PER_FRAME - 3200;
  double li = rms_dbfs(in + 1600, len), lo = rms_dbfs(out + skip, len);
  printf("frames %d (%d before flush), input %.1f dBFS, output %.1f dBFS\n", nf, early, li, lo);
  int ok = nf == N && early == N - 5 && fabs(lo - li) < 3.0;
  printf(ok ? "PASS\n" : "FAIL\n");
  return !ok;
}
