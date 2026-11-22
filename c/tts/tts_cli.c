/* sotto_tts: text -> sotto 1200 superframes (c/tts/sotto_tts.c).
 *   sotto_tts [-robot] [-trained] [-nowords] [-rate R] [-pitch P] [-params OUT.txt] [-pcm OUT.raw] "TEXT" OUT.sot
 * -trained: the trained duration and pitch trees instead of the rule prosody.
 * -nowords: callsigns from the table like any other word, not the whole-word units.
 * OUT.sot holds 6 bytes per 40 ms; -pcm decodes them (the fixed-point sotto 1200 decoder, the
 * K6's) to 8 kHz 16-bit mono; -params writes the frames before coding (one line per 20 ms:
 * code wi ei c1..c19) and the phones, for tools/tts_ccheck.py.
 * SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sotto_tts.h"
#include "../sotto.h"

int main(int argc, char **argv) {
  int robot = 0, trained = 0, words = 1, i = 1;
  double rate = 1, pitch = 1;
  const char *params = NULL, *pcm = NULL;
  for (; i < argc && argv[i][0] == '-' && argv[i][1]; i++) {
    if (!strcmp(argv[i], "-robot")) robot = 1;
    else if (!strcmp(argv[i], "-trained")) trained = 1;
    else if (!strcmp(argv[i], "-nowords")) words = 0;
    else if (!strcmp(argv[i], "-rate") && i + 1 < argc) rate = atof(argv[++i]);
    else if (!strcmp(argv[i], "-pitch") && i + 1 < argc) pitch = atof(argv[++i]);
    else if (!strcmp(argv[i], "-params") && i + 1 < argc) params = argv[++i];
    else if (!strcmp(argv[i], "-pcm") && i + 1 < argc) pcm = argv[++i];
    else break;
  }
  if (argc - i != 2) {
    fprintf(stderr, "usage: sotto_tts [-robot] [-trained] [-nowords] [-rate R] [-pitch P] [-params OUT.txt] [-pcm OUT.raw] \"TEXT\" OUT.sot\n");
    return 2;
  }
  struct sotto_tts *t = robot ? sotto_tts_create(sotto_tts_robot, sotto_tts_robot_len, sotto_tts_prosody, sotto_tts_prosody_len)
                              : sotto_tts_create(sotto_tts_diphone, sotto_tts_diphone_len, sotto_tts_prosody, sotto_tts_prosody_len);
  if (!t) return fprintf(stderr, "sotto_tts: bad table\n"), 1;
  sotto_tts_trained(t, trained);
  if (words && sotto_tts_set_words(t, sotto_tts_wordunits, sotto_tts_wordunits_len))
    return fprintf(stderr, "sotto_tts: bad word units\n"), 1;
  int n = sotto_tts_say(t, argv[i], rate, pitch);
  if (n < 0) return fprintf(stderr, "sotto_tts: out of memory\n"), 1;
  FILE *f = fopen(argv[i + 1], "wb");
  if (!f) return perror(argv[i + 1]), 1;
  fwrite(sotto_tts_superframes(t), 6, n, f);
  fclose(f);
  printf("%s\n%s\n%d superframes, %.2f s\n", sotto_tts_words(t), sotto_tts_phones(t), n, n * 0.04);
  if (params) {
    const int *code, *wi, *ei;
    const double *c;
    int nf = sotto_tts_frames(t, &code, &wi, &ei, &c);
    FILE *p = fopen(params, "w");
    if (!p) return perror(params), 1;
    fprintf(p, "%s\n", sotto_tts_phones(t));
    for (int k = 0; k < nf; k++) {
      fprintf(p, "%d %d %d", code[k], wi[k], ei[k]);
      for (int j = 0; j < 19; j++) fprintf(p, " %.6f", c[k * 19 + j]);
      fprintf(p, "\n");
    }
    fclose(p);
  }
  if (pcm) {
    FILE *o = fopen(pcm, "wb");
    struct sotto_lr_dec *d = sotto_lr_dec_create();
    short y[SOTTO_LR_SAMPLES_PER_FRAME];
    if (!o || !d) return perror(pcm), 1;
    for (int k = 0; k < n; k++) {
      sotto_lr_decode(d, sotto_tts_superframes(t) + 6 * k, 1, y);
      if (k >= SOTTO_LR_DEC_DELAY) fwrite(y, 2, SOTTO_LR_SAMPLES_PER_FRAME, o);
    }
    while (sotto_lr_dec_flush(d, y)) fwrite(y, 2, SOTTO_LR_SAMPLES_PER_FRAME, o);
    sotto_lr_dec_destroy(d);
    fclose(o);
  }
  sotto_tts_destroy(t);
  return 0;
}
