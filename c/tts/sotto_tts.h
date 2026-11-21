/* sotto-tts in C: text in, sotto 1200 superframes out (a port of tts/ in Python).
 *
 *   struct sotto_tts *t = sotto_tts_create(sotto_tts_diphone, sotto_tts_diphone_len,
 *                                          sotto_tts_prosody, sotto_tts_prosody_len);
 *   int n = sotto_tts_say(t, "This is AG7EW.", 1.0, 1.0);   // n superframes
 *   const unsigned char *sf = sotto_tts_superframes(t);      // n x 6 bytes, sotto 1200
 *
 * The steps are the Python prototype's (docs/sotto-tts.md): text -> phrases of words -> phones
 * with stress (NRL letter-to-sound rules and a small CMUdict lexicon; callsigns in NATO
 * phonetics) -> durations and pitch from the trained regression trees (tts/data/prosody.bin)
 * -> keyframes from a unit table (robot.stt or diphone.stt) -> 20 ms frames -> the fixed-point
 * sotto 1200 coder (c/fixed/sotto_fx_lr_enc.c, the K6's). Any sotto 1200 decoder plays them.
 * The synthesiser itself uses floating point; the tables, trees and coder are the K6's.
 * The data (rules, lexicon, tables, trees) is linked in from sotto_tts_data.c, which
 * tools/tts_cdata.py writes from tts/.
 * SPDX-License-Identifier: MIT */
#ifndef SOTTO_TTS_H
#define SOTTO_TTS_H

#ifdef __cplusplus
extern "C" {
#endif

struct sotto_tts;

extern const unsigned char sotto_tts_robot[], sotto_tts_diphone[], sotto_tts_prosody[];
extern const unsigned sotto_tts_robot_len, sotto_tts_diphone_len, sotto_tts_prosody_len;

/* table: a robot.stt or diphone.stt image; prosody: prosody.bin. Both must outlive the
   synthesiser. NULL on a bad image or no memory. */
struct sotto_tts *sotto_tts_create(const unsigned char *table, unsigned table_len,
                                   const unsigned char *prosody, unsigned prosody_len);
void sotto_tts_destroy(struct sotto_tts *t);

/* Synthesises text (ASCII); rate > 1 speaks faster, pitch scales the voice's pitch.
   Returns the number of superframes (6 bytes each, 40 ms), or -1 on no memory. */
int sotto_tts_say(struct sotto_tts *t, const char *text, double rate, double pitch);
const unsigned char *sotto_tts_superframes(const struct sotto_tts *t);

/* After sotto_tts_say: the phones with stress digits ("PAU DH IH1 S ..."), and per 20 ms
   frame the parameters before coding (voicing code, 7-bit pitch index, energy code, and
   19 DCT shape coefficients in dB) for comparing with the Python prototype. */
const char *sotto_tts_phones(const struct sotto_tts *t);
int sotto_tts_frames(const struct sotto_tts *t, const int **code, const int **wi,
                     const int **ei, const double **c);
/* the words as spoken (after numbers, callsigns, units), space separated, and each word's
   start time in seconds */
const char *sotto_tts_words(const struct sotto_tts *t);
int sotto_tts_word_times(const struct sotto_tts *t, const double **t0);

#ifdef __cplusplus
}
#endif
#endif
