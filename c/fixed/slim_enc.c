/* Bench for the slim sotto 1200 encoder: slim_enc [-a full|slim] [-c full|slim] [-d FIELDS.txt]
 * IN.raw OUT.bit. -a: whose analysis (the full fixed-point core's, or the slim one), -c: whose
 * coder. -d dumps every 20 ms frame's fields. With -DSLIM_TUNE, SLIM_TUNE="i=v,i=v" in the
 * environment sets tuning knobs.
 * SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../sotto.h"
#include "fx_internal.h"
#include "sotto_slim.h"

int main(int argc, char **argv) {
  int afull = 0, cfull = 0, amix = 0, i, n;
  (void)amix;
  const char *dump = NULL;
  FILE *fi, *fo, *fd = NULL;
  short x[80];
  unsigned char out[6];
  while (argc > 3 && argv[1][0] == '-') {
    if (!strcmp(argv[1], "-a")) afull = !strcmp(argv[2], "full"), amix = !strcmp(argv[2], "mix");
    else if (!strcmp(argv[1], "-c")) cfull = !strcmp(argv[2], "full");
    else if (!strcmp(argv[1], "-d")) dump = argv[2];
    else break;
    argv += 2, argc -= 2;
  }
  if (argc != 3) return fprintf(stderr, "usage: slim_enc [-a full|slim] [-c full|slim] [-d F.txt] IN.raw OUT.bit\n"), 2;
#ifdef SLIM_TUNE
  if (getenv("SLIM_TUNE")) {
    char s[256], *p;
    strncpy(s, getenv("SLIM_TUNE"), 255), s[255] = 0;
    for (p = strtok(s, ","); p; p = strtok(NULL, ",")) {
      int k, v;
      if (sscanf(p, "%d=%d", &k, &v) == 2 && k >= 0 && k < 32) slim_tune[k] = v;
    }
  }
#endif
  fi = fopen(argv[1], "rb"), fo = fopen(argv[2], "wb");
  if (!fi || !fo) return perror("open"), 1;
  if (dump) fd = fopen(dump, "w");
  struct sotto_enc *core = sotto_enc_create();
#ifdef SLIM_TUNE
  if (amix) {   /* -a mix: the full analysis's voicing and pitch, the slim envelope */
    extern const int16_t *slim_ovr;
    extern int slim_ovr_n;
    static int16_t ovr[2 * 4096];
    struct sotto_enc *c2 = sotto_enc_create();
    fx_fparams_t p;
    int m = 0;
    sotto_enc_set_no_shape(c2, 1);
    while (fread(x, sizeof(short), 80, fi) == 80) {
      sotto_enc_analyse_block(c2, x);
      while (sotto_enc_pop_frame_p(c2, NULL, &p) && m < 4096) ovr[2 * m] = p.code, ovr[2 * m + 1] = p.wi, m++;
    }
    sotto_enc_flush_core(c2);
    while (sotto_enc_pop_frame_p(c2, NULL, &p) && m < 4096) ovr[2 * m] = p.code, ovr[2 * m + 1] = p.wi, m++;
    slim_ovr = ovr, slim_ovr_n = m;
    rewind(fi);
  }
#endif
  struct sotto_lr_enc *lr = sotto_lr_enc_create_frames();
  slim_enc_t *se = calloc(1, slim_enc_bytes());
  slim_enc_init(se);
  sotto_enc_set_no_shape(core, 1);
  int end = 0, pass;
  for (;;) {
    slim_frame_t sf[4];
    int nf = 0;
    if (!end) {
      n = (int)fread(x, sizeof(short), 80, fi);
      if (n < 80) end = 1;
    }
    if (afull) {
      fx_fparams_t p;
      if (!end) sotto_enc_analyse_block(core, x);
      else if (end == 1) sotto_enc_flush_core(core), end = 2;
      fx_enc_frame_t ef;
      while (sotto_enc_pop_frame_p(core, &ef, &p) && nf < 4) {
        if (getenv("SLIM_HALVES")) {   /* the full analysis's halves: class, ln Wo Q16, level dB Q8 */
          static FILE *fh;
          int hh;
          if (!fh) fh = fopen(getenv("SLIM_HALVES"), "w");
          for (hh = 0; hh < 2; hh++)
            fprintf(fh, "%d %d %d\n", ef.snr[hh] == FX_SNR_NONE ? 0 : ef.snr[hh] < 8 * 256 ? 2 : 1, (int)ef.lwo[hh], (int)ef.en[hh]);
          fflush(fh);
        }
        sf[nf].code = p.code, sf[nf].wi = p.wi, sf[nf].ei = p.ei;
        for (i = 0; i < SLIM_NC; i++) sf[nf].c[i] = (int16_t)((p.c[i] + 128) >> 8);
        nf++;
      }
      if (end == 2 && nf == 0) end = 3;                      /* the flush's frames are all out */
    } else {
      if (!end) nf = slim_analyse10(se, x, &sf[0]);
      else {
        while (nf < 4 && slim_analyse_flush(se, &sf[nf])) nf++;
        end = 3;
      }
    }
    for (pass = 0; pass < nf; pass++) {
      const slim_frame_t *f = &sf[pass];
      if (fd) {
        fprintf(fd, "%d %d %d", f->code, f->wi, f->ei);
        for (i = 0; i < SLIM_NC; i++) fprintf(fd, " %d", f->c[i]);
        fprintf(fd, "\n");
      }
      if (cfull) {
        fx_fparams_t p;
        p.code = f->code, p.wi = f->wi, p.ei = f->ei;
        for (i = 0; i < SLIM_NC; i++) p.c[i] = (int32_t)f->c[i] * 256;
        sotto_lr_enc_push(lr, &p);
        while (sotto_lr_enc_pop(lr, out)) fwrite(out, 1, 6, fo);
      } else if (slim_coder_push(se, f, out)) fwrite(out, 1, 6, fo);
    }
    if (end == 3) break;
  }
  if (cfull) {
    sotto_lr_enc_end(lr);
    while (sotto_lr_enc_pop(lr, out)) fwrite(out, 1, 6, fo);
  } else if (slim_coder_flush(se, out)) fwrite(out, 1, 6, fo);
  fclose(fo);
  if (fd) fclose(fd);
#ifdef SLIM_TUNE
  if (getenv("SLIM_STAT")) {
    extern long slim_stat[4];
    fprintf(stderr, "searches %ld, compared %.1f a search, codebook vectors read %.1f a search\n", slim_stat[1],
            (double)slim_stat[0] / (slim_stat[1] ? slim_stat[1] : 1), (double)slim_stat[2] / (slim_stat[1] ? slim_stat[1] : 1));
  }
#endif
  return 0;
}
