/* Fixed-point math: table cos, log2 and exp2, dB conversions. See fx.h.
 * SPDX-License-Identifier: MIT */
#include "fx.h"
#include "fx_tables.h"

#ifdef FX_CHECK
#include <stdio.h>
#include <stdlib.h>
void fx_acc_check(fx_acc a) {
  if (a >= ((fx_acc)1 << 39) || a <= -((fx_acc)1 << 39)) {
    fprintf(stderr, "fx: accumulator beyond 40 bits: %lld\n", (long long)a);
    abort();
  }
}
#endif

int16_t fx_cos(uint32_t ph) {
  int i = (int)(ph >> 23);
  int32_t r = (int32_t)((ph >> 7) & 0xFFFF);
  int32_t c0 = fx_cos512[i], c1 = fx_cos512[(i + 1) & 511];
  return (int16_t)(c0 + (((c1 - c0) * r + 32768) >> 16));
}

/* position of the highest set bit of x > 0 (C55x: 31 - _lnorm) */
static int msb32(uint32_t x) {
  int n = 0;
  if (x >> 16) { n += 16; x >>= 16; }
  if (x >> 8) { n += 8; x >>= 8; }
  if (x >> 4) { n += 4; x >>= 4; }
  if (x >> 2) { n += 2; x >>= 2; }
  if (x >> 1) n += 1;
  return n;
}

int32_t fx_log2(uint32_t x) {
  int e = msb32(x);
  uint32_t m = x << (31 - e);                 /* [2^31, 2^32) */
  int i = (int)((m >> 23) & 255);
  int32_t r = (int32_t)((m >> 7) & 0xFFFF);
  int32_t a = fx_log2_tab[i], b = fx_log2_tab[i + 1];
  int32_t l = a + (int32_t)(((fx_acc)(b - a) * r + 32768) >> 16);   /* Q30 */
  return (int32_t)e * 65536 + ((l + 8192) >> 14);
}

int32_t fx_exp2(int32_t y, int q) {
  int32_t t = y + (int32_t)q * 65536;
  int32_t i = t >> 16;                        /* floor (arithmetic shift) */
  int32_t f = t & 0xFFFF;
  int j = (int)(f >> 8);
  int32_t r = f & 255;
  int32_t a = fx_exp2_tab[j], b = fx_exp2_tab[j + 1];
  int32_t m = a + (((b - a) * r + 128) >> 8);  /* Q30, [2^30, 2^31) */
  if (i >= 31) return INT32_MAX;
  int s = (int)(30 - i);
  if (s <= 0) return m;                        /* i == 30 */
  if (s >= 32) return 0;
  return (int32_t)(((fx_acc)m + ((fx_acc)1 << (s - 1))) >> s);
}

/* log2(10) / 20 x 2^16 and friends, rounded:
 *   dB Q8 -> log2 Q16:  x 256 log2(10)/20 = 42.5207 (amplitude), 85.0414 (power)
 *   log2 Q16 -> dB Q8:  x 20/log2(10)/256 = 0.0235180 (amplitude), 0.0117590 (power) */
int32_t fx_db_to_log2_amp(int32_t db) { return (int32_t)(((fx_acc)db * 2786641 + 32768) >> 16); }
int32_t fx_db_to_log2_pow(int32_t db) { return (int32_t)(((fx_acc)db * 5573281 + 32768) >> 16); }
int32_t fx_log2_to_db_amp(int32_t l2) { return (int32_t)(((fx_acc)l2 * 394566 + (1 << 23)) >> 24); }
int32_t fx_log2_to_db_pow(int32_t l2) { return (int32_t)(((fx_acc)l2 * 197283 + (1 << 23)) >> 24); }

int32_t fx_db_power_sum(const int32_t *v, int n) {
  int32_t mx = v[0];
  for (int i = 1; i < n; i++)
    if (v[i] > mx) mx = v[i];
  uint32_t s = 0;                              /* Q22, n <= 160 terms of at most 1 */
  for (int i = 0; i < n; i++) s += (uint32_t)fx_exp2(fx_db_to_log2_pow(v[i] - mx), 22);
  return mx + fx_log2_to_db_pow(fx_log2(s) - 22 * 65536);
}
