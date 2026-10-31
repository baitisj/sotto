/* sotto_dec IN.bit OUT.raw [GOOD.u8]: frames -> 8 kHz 16-bit mono raw speech.
 * GOOD.u8 holds one byte per frame, 0 for a frame that failed its CRC. The output is
 * aligned with the encoder input: the decoder's 20 ms of delay is removed.
 * SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <string.h>
#include "sotto.h"

int main(int argc, char **argv) {
  if (argc != 3 && argc != 4) {
    fprintf(stderr, "usage: %s IN.bit OUT.raw [GOOD.u8]\n", argv[0]);
    return 1;
  }
  FILE *in = strcmp(argv[1], "-") ? fopen(argv[1], "rb") : stdin;
  FILE *out = strcmp(argv[2], "-") ? fopen(argv[2], "wb") : stdout;
  FILE *gf = argc == 4 ? fopen(argv[3], "rb") : NULL;
  if (!in || !out || (argc == 4 && !gf)) {
    perror("sotto_dec");
    return 1;
  }
  struct sotto_dec *d = sotto_dec_create();
  unsigned char b[SOTTO_BYTES_PER_FRAME];
  short y[SOTTO_SAMPLES_PER_FRAME];
  long n = 0;
  while (fread(b, 1, sizeof b, in) == sizeof b) {
    int good = 1, c;
    if (gf && (c = fgetc(gf)) != EOF) good = c != 0;
    sotto_decode(d, b, good, y);
    if (n++) fwrite(y, sizeof(short), SOTTO_SAMPLES_PER_FRAME, out);
  }
  if (n) {
    sotto_dec_flush(d, y);
    fwrite(y, sizeof(short), SOTTO_SAMPLES_PER_FRAME, out);
  }
  sotto_dec_destroy(d);
  return 0;
}
