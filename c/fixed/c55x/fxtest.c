/* Checksums of the fixed-point primitives on pseudo-random inputs, to compare the C55x
 * build with the x86 one: cc -I.. fxtest.c ../fx_math.c ../fx_tables.c, and on the C55x
 * through tools/c55x_build.sh fxtest.
 * SPDX-License-Identifier: MIT */
#include <stdio.h>
#include "../fx.h"
#include "../fx_tables.h"

static uint32_t seed = 12345;
static uint32_t rnd32(void) { seed = seed * 1103515245ul + 12345ul; return seed; }
static uint32_t ck = 0;
static void mix(fx_acc v) {
  ck = ck * 31u + (uint32_t)(v & 0xFFFFFFFFu);
  ck = ck * 31u + (uint32_t)((v >> 32) & 0xFFu);
}

int main(void) {
  int i, k;
  static int32_t re[512], im[512];
  for (i = 0; i < 2000; i++) {           /* fx_sq32 for |a| < 2^19 */
    int32_t a = (int32_t)(rnd32() >> 13) - (1l << 18);
    mix(fx_sq32(a));
  }
  printf("sq32 %08lx\n", (unsigned long)ck); ck = 0;
  for (i = 0; i < 2000; i++) {
    int32_t a = (int32_t)(rnd32() >> 2) - (1l << 29);   /* |a| < 2^30 */
    int16_t b = (int16_t)(rnd32() >> 16);
    mix(fx_mul32x16(a, b));
  }
  printf("mul32x16 %08lx\n", (unsigned long)ck); ck = 0;
  for (i = 0; i < 200; i++) {
    fx_uacc r, q = fx_udiv_shl(1, 48, (rnd32() >> 4) | (1ul << 20), &r);
    mix((fx_acc)q); mix((fx_acc)r);
  }
  printf("udiv_shl %08lx\n", (unsigned long)ck); ck = 0;
  for (k = 0; k < 4; k++) {
    for (i = 0; i < 512; i++) { re[i] = (int32_t)(rnd32() >> 9) - (1l << 22); im[i] = 0; }
    fx_fft(re, im, 512);
    for (i = 0; i < 512; i++) { mix(re[i]); mix(im[i]); }
  }
  printf("fft %08lx\n", (unsigned long)ck); ck = 0;
  for (i = 0; i < 2000; i++) {
    uint32_t x = rnd32() | 1;
    mix(fx_log2(x)); mix(fx_exp2((int32_t)(rnd32() >> 8) - (1l << 23), 4));
  }
  printf("log2/exp2 %08lx\n", (unsigned long)ck); ck = 0;
  for (i = 0; i < 2000; i++) {
    fx_acc a = (fx_acc)(int32_t)rnd32() * 64 + (rnd32() & 63);
    mix(fx_rshr(a, 1 + (int)(rnd32() >> 28)));
    mix(fx_log2_acc((fx_uacc)(a < 0 ? -a : a) + 1));
  }
  printf("rshr/log2_acc %08lx\n", (unsigned long)ck);
  ck = 0;
  for (k = 0; k < 50; k++) {              /* a 48-term 32 x 16 dot product as two 16 x 16 sums */
    static int32_t a[48];
    static int16_t b[48];
    fx_acc hi = 0, lo = 0;
    for (i = 0; i < 48; i++) { a[i] = (int32_t)(rnd32() >> 9) - (1l << 22); b[i] = (int16_t)(rnd32() >> 16); }
    for (i = 0; i < 48; i++) { hi += (fx_acc)FX_HI(a[i]) * b[i]; lo += (fx_acc)FX_LO(a[i]) * b[i]; }
    mix(hi); mix(lo);
  }
  printf("dot32x16 %08lx\n", (unsigned long)ck);
  printf("done\n");
  return 0;
}
