/* WebAssembly entry points for sotto-tts (c/tts/sotto_tts.c): the text-to-speech page
 * (docs/tts.html) types text into tts_text(), calls tts_say() and plays tts_pcm(). Everything
 * the K6 would run: the unit tables and prosody trees, the fixed-point sotto 1200 coder, and
 * the fixed-point decoder (the same bits and samples as c/tts/sotto_tts -pcm).
 * SPDX-License-Identifier: MIT */
#include <stdlib.h>
#include <string.h>
#include "../sotto.h"
#include "../tts/sotto_tts.h"

#define EXPORT(name) __attribute__((export_name(#name)))
#define MAXTEXT 8192

static char text[MAXTEXT];
static struct sotto_tts *tts[2];
static short *pcm;
static int npcm;

/* the buffer the page writes its text into (NUL-terminated ASCII, up to MAXTEXT - 1 bytes) */
EXPORT(tts_text) char *tts_text(void) { return text; }
EXPORT(tts_text_max) int tts_text_max(void) { return MAXTEXT; }

/* table 0: the diphone table (37 KB), 1: the robot table (493 B); trained 0: rule prosody,
   1: the trained trees; nowords 1: callsigns from the table, not the whole-word units. Returns the number of superframes, or -1. The speech is then in
   tts_pcm() (8 kHz, tts_npcm() samples). */
EXPORT(tts_say) int tts_say(int table, double rate, double pitch, int trained, int nowords) {
  table = table ? 1 : 0;
  if (!tts[table])
    tts[table] = table ? sotto_tts_create(sotto_tts_robot, sotto_tts_robot_len, sotto_tts_prosody, sotto_tts_prosody_len)
                       : sotto_tts_create(sotto_tts_diphone, sotto_tts_diphone_len, sotto_tts_prosody, sotto_tts_prosody_len);
  struct sotto_tts *t = tts[table];
  if (!t) return -1;
  text[MAXTEXT - 1] = 0;
  sotto_tts_trained(t, trained);
  if (sotto_tts_set_words(t, nowords ? NULL : sotto_tts_wordunits, sotto_tts_wordunits_len)) return -1;
  int n = sotto_tts_say(t, text, rate, pitch);
  if (n < 0) return -1;
  free(pcm);
  pcm = malloc((size_t)(n + 4) * SOTTO_LR_SAMPLES_PER_FRAME * sizeof *pcm);
  struct sotto_lr_dec *d = sotto_lr_dec_create();
  if (!pcm || !d) return free(d), -1;
  npcm = 0;
  const unsigned char *sf = sotto_tts_superframes(t);
  for (int k = 0; k < n; k++) {
    sotto_lr_decode(d, sf + SOTTO_BYTES_PER_FRAME * k, 1, pcm + npcm);
    if (k >= SOTTO_LR_DEC_DELAY) npcm += SOTTO_LR_SAMPLES_PER_FRAME;
  }
  while (npcm < (n + 2) * SOTTO_LR_SAMPLES_PER_FRAME && sotto_lr_dec_flush(d, pcm + npcm)) npcm += SOTTO_LR_SAMPLES_PER_FRAME;
  sotto_lr_dec_destroy(d);
  return n;
}

EXPORT(tts_pcm) short *tts_pcm(void) { return pcm; }
EXPORT(tts_npcm) int tts_npcm(void) { return npcm; }
EXPORT(tts_superframes) const unsigned char *tts_superframes(int table) { return sotto_tts_superframes(tts[table ? 1 : 0]); }
EXPORT(tts_phones) const char *tts_phones(int table) { return sotto_tts_phones(tts[table ? 1 : 0]); }
EXPORT(tts_words) const char *tts_words(int table) { return sotto_tts_words(tts[table ? 1 : 0]); }
EXPORT(tts_word_times) const double *tts_word_times(int table) {
  const double *t0;
  sotto_tts_word_times(tts[table ? 1 : 0], &t0);
  return t0;
}
EXPORT(tts_table_bytes) int tts_table_bytes(int table) { return table ? (int)sotto_tts_robot_len : (int)sotto_tts_diphone_len; }
EXPORT(tts_prosody_bytes) int tts_prosody_bytes(void) { return (int)sotto_tts_prosody_len; }
