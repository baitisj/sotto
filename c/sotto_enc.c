/* sotto_enc IN.raw OUT.bit: 8 kHz 16-bit mono raw speech -> 6 bytes per 20 ms frame.
 * SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <string.h>
#include "sotto.h"

int main(int argc, char **argv) {
  if (argc != 3) {
    fprintf(stderr, "usage: %s IN.raw OUT.bit   (- for stdin/stdout)\n", argv[0]);
    return 1;
  }
  FILE *in = strcmp(argv[1], "-") ? fopen(argv[1], "rb") : stdin;
  FILE *out = strcmp(argv[2], "-") ? fopen(argv[2], "wb") : stdout;
  if (!in || !out) {
    perror("sotto_enc");
    return 1;
  }
  struct sotto_enc *e = sotto_enc_create();
  short x[SOTTO_SAMPLES_PER_FRAME];
  unsigned char b[SOTTO_BYTES_PER_FRAME];
  size_t n;
  while ((n = fread(x, sizeof(short), SOTTO_SAMPLES_PER_FRAME, in)) == SOTTO_SAMPLES_PER_FRAME)
    if (sotto_encode(e, x, b)) fwrite(b, 1, sizeof b, out);
  /* a last half frame (80 samples) is analysed too; anything shorter is dropped */
  if (n >= SOTTO_SAMPLES_PER_FRAME / 2) {
    memset(x + n, 0, (SOTTO_SAMPLES_PER_FRAME - n) * sizeof(short));
    sotto_encode_half(e, x);
  }
  while (sotto_enc_flush(e, b)) fwrite(b, 1, sizeof b, out);
  sotto_enc_destroy(e);
  return 0;
}
