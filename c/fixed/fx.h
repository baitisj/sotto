/* Fixed-point basics for the sotto DSP build.
 *
 * Written for the TI C55x (no FPU, 16-bit int and char, 32-bit long, 40-bit accumulators)
 * and tested on x86. Rules that keep the two the same:
 *  - only exact-width types (int16_t, int32_t, uint32_t) for values; plain int only for
 *    loop counters and small indices (|x| < 32768);
 *  - sums of products go in fx_acc. On x86 that is int64_t. On the C55x it is the 40-bit
 *    accumulator, so every fx_acc sum must stay below 2^39 in magnitude. Build with
 *    -DFX_CHECK to check that bound at run time (fx_acc_check);
 *  - formats are written Qn: an integer x stands for x / 2^n.
 *
 * Common formats in this code:
 *  - levels in dB, Q8 in int32_t;
 *  - frequencies as turns per sample, Q32 in uint32_t (2^32 = one turn, 2 pi radians), so
 *    phase accumulators wrap for free;
 *  - log2 values, Q16 in int32_t.
 * SPDX-License-Identifier: MIT */
#ifndef SOTTO_FX_H
#define SOTTO_FX_H
#include <stdint.h>

typedef int64_t fx_acc;

#ifdef FX_CHECK
void fx_acc_check(fx_acc a);
#define FX_ACC_CHECK(a) fx_acc_check(a)
#else
#define FX_ACC_CHECK(a) ((void)0)
#endif

/* round-to-nearest right shift (n >= 1) */
static inline int32_t fx_rshr(fx_acc x, int n) { return (int32_t)((x + ((fx_acc)1 << (n - 1))) >> n); }

/* cos and sin of a Q32 phase, Q15, from the 512-point table with linear interpolation */
int16_t fx_cos(uint32_t ph);
static inline int16_t fx_sin(uint32_t ph) { return fx_cos(ph - 0x40000000u); }

/* log2(x) for x > 0, Q16 */
int32_t fx_log2(uint32_t x);
/* 2^(y / 2^16) * 2^q, rounded and saturated to int32 (q may be negative) */
int32_t fx_exp2(int32_t y, int q);

/* dB (Q8) to log2 (Q16) of the amplitude (dB / 20) or the power (dB / 10), and back */
int32_t fx_db_to_log2_amp(int32_t db);
int32_t fx_db_to_log2_pow(int32_t db);
int32_t fx_log2_to_db_amp(int32_t l2);
int32_t fx_log2_to_db_pow(int32_t l2);

/* 10 log10(sum 10^(v[i]/10)) for dB values in Q8, without overflow */
int32_t fx_db_power_sum(const int32_t *v, int n);

#endif
