/* gcc 15 vectorizer check: the stage-A speaker-shape loop of c/fixed/sotto_fx_hiss.c:1348 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef int64_t fx_acc;
static inline int32_t fx_rshr(fx_acc x, int n) { return (int32_t)((x + ((fx_acc)1 << (n - 1))) >> n); }
int32_t m0[16];
int16_t vt[48];
__attribute__((noinline)) void loop(const int16_t *pc, const int32_t *pr, int32_t ref, int32_t *out) {
  int b, c;
  for (b = 0; b < 16; b++) {
    fx_acc corr = (fx_acc)m0[b] * 16384;
    for (c = 0; c < 3; c++) corr += (fx_acc)pc[c] * vt[c * 16 + b];
    out[b] = pr[b] + ref + fx_rshr(corr, 14);
  }
}
__attribute__((noinline, optimize("O0"))) void ref_loop(const int16_t *pc, const int32_t *pr, int32_t ref, int32_t *out) {
  int b, c;
  for (b = 0; b < 16; b++) {
    fx_acc corr = (fx_acc)m0[b] * 16384;
    for (c = 0; c < 3; c++) corr += (fx_acc)pc[c] * vt[c * 16 + b];
    out[b] = pr[b] + ref + fx_rshr(corr, 14);
  }
}
int main(void) {
  int bad = 0, t, b;
  srand(1);
  for (t = 0; t < 100000; t++) {
    int16_t pc[3]; int32_t pr[16], o1[16], o2[16], ref = rand() % 4000 - 2000;
    for (b = 0; b < 16; b++) m0[b] = rand() % 20000 - 10000, pr[b] = rand() % 4000 - 2000;
    for (b = 0; b < 48; b++) vt[b] = (int16_t)(rand() % 65536 - 32768);
    for (b = 0; b < 3; b++) pc[b] = (int16_t)(rand() % 30000 - 15000);
    loop(pc, pr, ref, o1); ref_loop(pc, pr, ref, o2);
    for (b = 0; b < 16; b++) if (o1[b] != o2[b]) { if (bad < 5) printf("t %d b %d: %d vs %d\n", t, b, o1[b], o2[b]); bad++; }
  }
  printf("%d mismatches\n", bad);
  return bad != 0;
}
