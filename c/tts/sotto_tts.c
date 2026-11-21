/* sotto-tts in C: a port of the Python prototype (tts/frontend.py, tts/lts.py, tts/prosody.py,
 * tts/table.py, tts/synth.py); see sotto_tts.h. Each function names the Python one it follows,
 * and tools/tts_ccheck.py compares the two on test sentences (the phones and the frames' codes,
 * pitch and energy indices match; the shapes to rounding).
 * SPDX-License-Identifier: MIT */
#include <ctype.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sotto_tts.h"
#include "../sotto.h"
#include "../fixed/fx.h"
#include "../fixed/fx_internal.h"

struct sotto_lr_enc *sotto_lr_enc_create_frames(void);
void sotto_lr_enc_push(struct sotto_lr_enc *e, const fx_fparams_t *p);
void sotto_lr_enc_end(struct sotto_lr_enc *e);
int sotto_lr_enc_pop(struct sotto_lr_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]);
#include "../fixed/fx_tables.h"

extern const char sotto_tts_rules[], sotto_tts_lexicon[];

#define NC 19
#define FRAME 0.02
#define PI_D 3.14159265358979323846
#define YESNO_RISE 0.4       /* log pitch added at the end of a yes/no question (prosody.Model) */

/* ------------------------------------------------------------------ phones (tts/phones.py) */
enum { NP = 42, PAU = 0 };
static const char *const PH[NP] = {
  "PAU", "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW",
  "AX", "AXR", "B", "CH", "D", "DH", "F", "G", "HH", "JH", "K", "L", "M", "N", "NG", "P", "R", "S",
  "SH", "T", "TH", "V", "W", "Y", "Z", "ZH"};
enum { AA = 1, AE, AH, AO, AW, AY, EH, ER, EY, IH, IY, OW, OY, UH, UW, AX, AXR, B, CH, D, DH, F, G,
       HH, JH, K, L, M, N, NG, P, R, S, SH, T, TH, V, W, Y, Z, ZH };

static int vowel(int p) { return p >= AA && p <= AXR; }
static int stop(int p) { return p == P || p == B || p == T || p == D || p == K || p == G; }
static int affricate(int p) { return p == CH || p == JH; }
static int fricative(int p) {
  return p == F || p == V || p == TH || p == DH || p == S || p == Z || p == SH || p == ZH || p == HH;
}
static int nasal(int p) { return p == M || p == N || p == NG; }
static int liquid(int p) { return p == L || p == R || p == W || p == Y; }
static int diphthong(int p) { return p == AW || p == AY || p == EY || p == OW || p == OY; }
static int voiced_c(int p) {
  return p == B || p == D || p == G || p == JH || p == V || p == DH || p == Z || p == ZH || p == M ||
         p == N || p == NG || p == L || p == R || p == W || p == Y;
}

static int phone_id(const char *s, int n) {
  for (int i = 0; i < NP; i++)
    if ((int)strlen(PH[i]) == n && !strncmp(PH[i], s, n)) return i;
  return -1;
}

/* ------------------------------------------------------------------ growable arrays */
#define GROW(arr, n, cap) do { \
    if ((n) >= (cap)) { \
      int c_ = (cap) ? 2 * (cap) : 64; \
      void *p_ = realloc((arr), c_ * sizeof *(arr)); \
      if (!p_) return -1; \
      (arr) = p_, (cap) = c_; \
    } \
  } while (0)

/* ------------------------------------------------------------------ letter-to-sound (tts/lts.py) */
#define MAXPH 48
typedef struct { unsigned char p, s; } phs_t;     /* phone, stress */

typedef struct { const char *left, *match, *right; int nl, nm, nr; unsigned char ph[8]; int nph; } rule_t;
static rule_t *g_rules;
static int g_nrules;

static int is_in(int c, const char *set) { return c && strchr(set, c) != NULL; }
#define VOWEL_L "AEIOU"
#define CONS_L "BCDFGHJKLMNPQRSTVWXYZ"
#define VOICED_L "BDGJLMNRVWZ"
#define FRONT_L "EIY"
#define DOUBLE_SKIP "BDFGKLMNPRTVZ"

static int parse_rules(void) {
  static int done;
  if (done) return 0;
  int cap = 0;
  const char *s = sotto_tts_rules;
  while (*s) {
    const char *e = strchr(s, '\n');
    int n = e ? (int)(e - s) : (int)strlen(s);
    if (n > 0 && !(s[0] == '#' && n == 2)) {
      const char *lb = memchr(s, '[', n), *rb = lb ? memchr(lb, ']', n - (lb - s)) : NULL;
      const char *eq = rb ? memchr(rb, '=', n - (rb - s)) : NULL;
      if (!eq) return -1;
      GROW(g_rules, g_nrules, cap);
      rule_t *r = &g_rules[g_nrules];
      r->left = s, r->nl = (int)(lb - s);
      r->match = lb + 1, r->nm = (int)(rb - lb - 1);
      r->right = rb + 1, r->nr = (int)(eq - rb - 1);
      r->nph = 0;
      const char *q = eq + 1, *end = s + n;
      while (q < end) {
        while (q < end && *q == ' ') q++;
        const char *w = q;
        while (q < end && *q != ' ') q++;
        if (q > w) r->ph[r->nph++] = (unsigned char)phone_id(w, (int)(q - w));
      }
      g_nrules++;
    }
    s += n + (e ? 1 : 0);
  }
  done = 1;
  return 0;
}

static int right_ctx(const char *ctx, int nc, const char *w, int len, int i) {
  for (int k = 0; k < nc; k++) {
    char c = ctx[k];
    if (c == '#') {
      if (i >= len || !is_in(w[i], VOWEL_L)) return 0;
      while (i < len && is_in(w[i], VOWEL_L)) i++;
    } else if (c == ':') {
      while (i < len && is_in(w[i], CONS_L)) i++;
    } else if (c == '^') {
      if (i >= len || !is_in(w[i], CONS_L)) return 0;
      i++;
    } else if (c == '.') {
      if (i >= len || !is_in(w[i], VOICED_L)) return 0;
      i++;
    } else if (c == '+') {
      if (i >= len || !is_in(w[i], FRONT_L)) return 0;
      i++;
    } else if (c == '%') {
      static const char *const suf[] = {"ING", "ELY", "ER", "ES", "ED", "E"};
      for (int j = 0; j < 6; j++) {
        int m = (int)strlen(suf[j]);
        if (i + m <= len && !strncmp(w + i, suf[j], m) && (i + m >= len || !isalpha((unsigned char)w[i + m])))
          return right_ctx(ctx + k + 1, nc - k - 1, w, len, i + m);
      }
      return 0;
    } else {
      if (i >= len || w[i] != c) return 0;
      i++;
    }
  }
  return 1;
}

static int left_ctx(const char *ctx, int nc, const char *w, int i) {
  i--;
  for (int k = nc - 1; k >= 0; k--) {
    char c = ctx[k];
    if (c == '#') {
      if (i < 0 || !is_in(w[i], VOWEL_L)) return 0;
      while (i >= 0 && is_in(w[i], VOWEL_L)) i--;
    } else if (c == ':') {
      while (i >= 0 && is_in(w[i], CONS_L)) i--;
    } else if (c == '^') {
      if (i < 0 || !is_in(w[i], CONS_L)) return 0;
      i--;
    } else if (c == '.') {
      if (i < 0 || !is_in(w[i], VOICED_L)) return 0;
      i--;
    } else if (c == '+') {
      if (i < 0 || !is_in(w[i], FRONT_L)) return 0;
      i--;
    } else if (c == '&') {
      if (i >= 1 && (!strncmp(w + i - 1, "CH", 2) || !strncmp(w + i - 1, "SH", 2))) i -= 2;
      else if (i >= 0 && is_in(w[i], "SCGZXJ")) i--;
      else return 0;
    } else if (c == '@') {
      if (i >= 1 && (!strncmp(w + i - 1, "TH", 2) || !strncmp(w + i - 1, "CH", 2) || !strncmp(w + i - 1, "SH", 2))) i -= 2;
      else if (i >= 0 && is_in(w[i], "TSRDLZNJ")) i--;
      else return 0;
    } else {
      if (i < 0 || w[i] != c) return 0;
      i--;
    }
  }
  return 1;
}

/* lts.letters_to_phones: word (lower case letters and apostrophes) -> phones */
static int letters_to_phones(const char *word, unsigned char *out) {
  char w[80];
  int len = 0, n = 0;
  w[len++] = ' ';
  for (const char *c = word; *c && len < 77; c++) w[len++] = (char)toupper((unsigned char)*c);
  w[len++] = ' ';
  w[len] = 0;
  int i = 1;
  while (i < len - 1) {
    char ch = w[i];
    if (is_in(ch, DOUBLE_SKIP) && w[i - 1] == ch) {
      i++;
      continue;
    }
    int hit = 0;
    for (int r = 0; r < g_nrules; r++) {
      const rule_t *R = &g_rules[r];
      if (R->match[0] == ch && i + R->nm <= len && !strncmp(w + i, R->match, R->nm) && left_ctx(R->left, R->nl, w, i) &&
          right_ctx(R->right, R->nr, w, len, i + R->nm)) {
        for (int k = 0; k < R->nph && n < MAXPH; k++) out[n++] = R->ph[k];
        i += R->nm;
        hit = 1;
        break;
      }
    }
    if (!hit) i++;
  }
  return n;
}

static int ends_with(const char *w, const char *s) {
  size_t a = strlen(w), b = strlen(s);
  return a >= b && !strcmp(w + a - b, s);
}

/* lts.stress: a guess of primary stress from the word's shape */
static int stress(const char *word, const unsigned char *ph, int n, phs_t *out) {
  static const char *const PREFIXES[] = {"A", "BE", "DE", "RE", "UN", "IN", "EX", "CON", "COM", "PRE", "DIS", "MIS", "TRANS"};
  static const char *const SUFFIX_PRE[] = {"TION", "SION", "TIAN", "CIAN", "IC", "ICAL", "ITY", "IAL", "IAN", "IOUS", "EOUS"};
  int vi[MAXPH], vall[MAXPH], nvi = 0, nva = 0;
  for (int k = 0; k < n; k++) {
    if (vowel(ph[k])) {
      vall[nva++] = k;
      if (ph[k] != AX && ph[k] != AXR) vi[nvi++] = k;
    }
  }
  if (!nva) {
    for (int k = 0; k < n; k++) out[k].p = ph[k], out[k].s = 0;
    return n;
  }
  char w[80];
  int len = 0;
  for (const char *c = word; *c && len < 79; c++) w[len++] = (char)toupper((unsigned char)*c);
  w[len] = 0;
  int target = -1;
  if (nva >= 3) {
    for (int j = 0; j < 11; j++) {
      const char *suf = SUFFIX_PRE[j];
      if (ends_with(w, suf)) {
        int nv = 0;
        for (const char *c = suf; *c; c++) nv += is_in(*c, "AEIOU");
        nv -= (j < 4 || j >= 9) ? 1 : 0;      /* TION SION TIAN CIAN IOUS EOUS */
        if (nv >= 0) {
          int ix = nva - 1 - nv - 1;
          target = vall[ix < 0 ? 0 : ix];
        }
        break;
      }
    }
  }
  if (target < 0 && nva >= 2) {
    for (int j = 0; j < 13; j++) {
      size_t m = strlen(PREFIXES[j]);
      if (!strncmp(w, PREFIXES[j], m) && (size_t)len > m + 2) {
        target = vall[1];
        break;
      }
    }
  }
  if (target < 0) target = nvi ? vi[0] : vall[0];
  for (int k = 0; k < n; k++) {
    int p = ph[k], s = k == target;
    if (p == AH && !s) p = AX;
    if (p == ER && !s) p = AXR;
    if (p == AX && s) p = AH;
    out[k].p = (unsigned char)p, out[k].s = (unsigned char)s;
  }
  return n;
}

/* ------------------------------------------------------------------ lexicon */
typedef struct { const char *w; int nw; const char *ph; } lex_t;
static lex_t *g_lex;
static int g_nlex;

static int parse_lexicon(void) {
  static int done;
  if (done) return 0;
  int cap = 0;
  const char *s = sotto_tts_lexicon;
  while (*s) {
    const char *e = strchr(s, '\n');
    int n = e ? (int)(e - s) : (int)strlen(s);
    if (n > 0 && s[0] != ';') {
      const char *sp = memchr(s, ' ', n);
      if (sp) {
        GROW(g_lex, g_nlex, cap);
        g_lex[g_nlex].w = s, g_lex[g_nlex].nw = (int)(sp - s), g_lex[g_nlex].ph = sp + 1;
        g_nlex++;
      }
    }
    s += n + (e ? 1 : 0);
  }
  done = 1;
  return 0;
}

static const lex_t *lex_find(const char *w) {
  int n = (int)strlen(w);
  for (int i = 0; i < g_nlex; i++)
    if (g_lex[i].nw == n && !strncmp(g_lex[i].w, w, n)) return &g_lex[i];
  return NULL;
}

/* phones.from_arpabet over a lexicon line */
static int lex_phones(const lex_t *L, phs_t *out) {
  const char *q = L->ph;
  int n = 0;
  while (*q && *q != '\n' && n < MAXPH) {
    while (*q == ' ') q++;
    const char *w = q;
    while (*q && *q != ' ' && *q != '\n') q++;
    int len = (int)(q - w), st = 0;
    if (!len) break;
    if (isdigit((unsigned char)w[len - 1])) st = w[len - 1] - '0', len--;
    int p = phone_id(w, len);
    if (p == AH && st == 0) p = AX;
    if (p == ER && st == 0) p = AXR;
    if (p < 0) continue;
    out[n].p = (unsigned char)p, out[n].s = (unsigned char)st;
    n++;
  }
  return n;
}

/* frontend.pronounce */
static int pronounce(const char *word, phs_t *out) {
  const lex_t *L = lex_find(word);
  if (L) return lex_phones(L, out);
  char w[64];
  int n = 0;
  for (const char *c = word; *c && n < 63; c++)
    if ((*c >= 'a' && *c <= 'z') || *c == '\'') w[n++] = *c;
  w[n] = 0;
  if (!n) return 0;
  L = lex_find(w);
  if (L) return lex_phones(L, out);
  unsigned char ph[MAXPH];
  int np = letters_to_phones(w, ph);
  return stress(w, ph, np, out);
}

/* ------------------------------------------------------------------ front end (tts/frontend.py) */
static const char *const NATO[26] = {
  "alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliett",
  "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango",
  "uniform", "victor", "whiskey", "xray", "yankee", "zulu"};
static const char *const DIGITS[10] = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"};
static const char *const TEENS[10] = {"ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"};
static const char *const TENS[10] = {"", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"};
static const char *const LETTER[26] = {
  "ay", "bee", "see", "dee", "ee", "ef", "gee", "aitch", "eye", "jay", "kay", "el", "em", "en",
  "oh", "pee", "cue", "ar", "es", "tee", "you", "vee", "doubleyou", "ex", "why", "zee"};
static const char *const UNITS[][4] = {
  {"mhz", "megahertz"}, {"khz", "kilohertz"}, {"hz", "hertz"}, {"ghz", "gigahertz"},
  {"db", "dee", "bee"}, {"dbm", "dee", "bee", "em"}, {"w", "watts"}, {"km", "kilometers"},
  {"utc", "you", "tee", "see"}, {"pt", "pacific"}};
static const char FUNCTION[] =
  " a an the of to in on at by for from with as and or but nor so if than then that this these"
  " those is am are was were be been being have has had do does did can could will would shall"
  " should may might must i me my we us our you your he him his she her it its they them their"
  " there here not no what which who whom whose when where how all any some each every into onto"
  " up down out over off about just ";
static const char AUX[] = " is are was were do does did can could will would shall should have has had am may might must ";

static int in_list(const char *list, const char *w) {
  char b[72];
  if (strlen(w) > 64) return 0;
  snprintf(b, sizeof b, " %s ", w);
  return strstr(list, b) != NULL;
}

enum { C_FUNC = 0, C_CONTENT = 1, C_SPELL = 2 };
typedef struct { char text[64]; int content; } xw_t;   /* an expanded word */

#define MAXX 64
static int addw(xw_t *o, int n, const char *w, int content) {
  if (n >= MAXX) return n;
  snprintf(o[n].text, sizeof o[n].text, "%s", w);
  o[n].content = content;
  return n + 1;
}

/* frontend.cardinal: 0..9999 as words */
static int cardinal(int v, xw_t *o, int n) {
  if (v < 10) return addw(o, n, DIGITS[v], C_CONTENT);
  if (v < 20) return addw(o, n, TEENS[v - 10], C_CONTENT);
  if (v < 100) {
    n = addw(o, n, TENS[v / 10], C_CONTENT);
    return v % 10 ? addw(o, n, DIGITS[v % 10], C_CONTENT) : n;
  }
  if (v < 1000) {
    n = addw(o, n, DIGITS[v / 100], C_CONTENT);
    n = addw(o, n, "hundred", C_CONTENT);
    return v % 100 ? cardinal(v % 100, o, n) : n;
  }
  if (v % 1000 == 0) {
    n = cardinal(v / 1000, o, n);
    return addw(o, n, "thousand", C_CONTENT);
  }
  if (v >= 1100 && v < 10000 && (v / 100) % 10) {
    int hi = v / 100, lo = v % 100;
    n = cardinal(hi, o, n);
    if (lo == 0) return addw(o, n, "hundred", C_CONTENT);
    if (lo < 10) n = addw(o, n, "oh", C_CONTENT);
    return cardinal(lo, o, n);
  }
  n = cardinal(v / 1000, o, n);
  n = addw(o, n, "thousand", C_CONTENT);
  return cardinal(v % 1000, o, n);
}

static int all_class(const char *s, int (*f)(int)) {
  if (!*s) return 0;
  for (; *s; s++)
    if (!f((unsigned char)*s)) return 0;
  return 1;
}

/* ^[A-Za-z]{1,2}[0-9]{1,2}[A-Za-z]{1,4}(/[A-Za-z0-9]{1,4})?$ */
static int is_callsign(const char *t) {
  int i = 0, k;
  for (k = 0; isalpha((unsigned char)t[i]) && k < 3; k++) i++;
  if (k < 1 || k > 2) return 0;
  for (k = 0; isdigit((unsigned char)t[i]) && k < 3; k++) i++;
  if (k < 1 || k > 2) return 0;
  for (k = 0; isalpha((unsigned char)t[i]) && k < 5; k++) i++;
  if (k < 1 || k > 4) return 0;
  if (!t[i]) return 1;
  if (t[i] != '/') return 0;
  i++;
  for (k = 0; isalnum((unsigned char)t[i]) && k < 5; k++) i++;
  return k >= 1 && k <= 4 && !t[i];
}

static int is_decimal(const char *t) {
  int i = 0, a = 0, b = 0;
  while (isdigit((unsigned char)t[i])) i++, a++;
  if (!a || t[i] != '.') return 0;
  i++;
  while (isdigit((unsigned char)t[i])) i++, b++;
  return b && !t[i];
}

static int digits_dots(const char *t) {
  if (!*t) return 0;
  for (; *t; t++)
    if (!isdigit((unsigned char)*t) && *t != '.') return 0;
  return 1;
}

static int is_upper_str(const char *t) {   /* str.isupper: some cased letter, none lower case */
  int any = 0;
  for (; *t; t++) {
    if (islower((unsigned char)*t)) return 0;
    if (isupper((unsigned char)*t)) any = 1;
  }
  return any;
}

/* frontend.expand: one raw token -> words in spoken order */
static int expand(const char *t, const char *prev, xw_t *o, int n) {
  if (is_callsign(t)) {
    for (const char *c = t; *c; c++) {
      if (isdigit((unsigned char)*c)) n = addw(o, n, DIGITS[*c - '0'], C_SPELL);
      else if (*c == '/') n = addw(o, n, "stroke", C_SPELL);
      else n = addw(o, n, NATO[toupper((unsigned char)*c) - 'A'], C_SPELL);
    }
    return n;
  }
  if (is_decimal(t)) {
    for (const char *c = t; *c; c++)
      n = addw(o, n, *c == '.' ? "point" : DIGITS[*c - '0'], C_CONTENT);
    return n;
  }
  if (all_class(t, isdigit)) {
    if (strlen(t) > 4 || t[0] == '0') {
      for (const char *c = t; *c; c++) n = addw(o, n, DIGITS[*c - '0'], C_CONTENT);
      return n;
    }
    return cardinal(atoi(t), o, n);
  }
  char low[64];
  int L = 0;
  for (const char *c = t; *c && L < 63; c++) low[L++] = (char)tolower((unsigned char)*c);
  low[L] = 0;
  int unit = -1;
  for (int u = 0; u < 10; u++)
    if (!strcmp(low, UNITS[u][0])) unit = u;
  if (unit >= 0 && ((prev && digits_dots(prev)) || in_list(" mhz khz ghz hz dbm utc ", low))) {
    for (int k = 1; k < 4 && UNITS[unit][k]; k++) n = addw(o, n, UNITS[unit][k], C_CONTENT);
    return n;
  }
  if (is_upper_str(t) && L >= 2 && L <= 5 && !lex_find(low) && all_class(t, isalpha)) {
    for (const char *c = t; *c; c++) n = addw(o, n, LETTER[*c - 'A'], C_CONTENT);
    return n;
  }
  {   /* ^[0-9]+[a-zA-Z]+$: 5W, 20m */
    int i = 0;
    while (isdigit((unsigned char)t[i])) i++;
    if (i > 0 && t[i] && all_class(t + i, isalpha)) {
      char num[32];
      if (i > 31) i = 31;
      memcpy(num, t, i);
      num[i] = 0;
      n = expand(num, NULL, o, n);
      return expand(t + i, num, o, n);
    }
  }
  return addw(o, n, low, in_list(FUNCTION, low) ? C_FUNC : C_CONTENT);
}

typedef struct { char text[64]; phs_t ph[MAXPH]; int nph, content, spell; } word_t;
typedef struct { int w0, nw; char end; } phrase_t;

typedef struct {
  int p, stress, content, word, phrase, spell, gw;   /* gw: index in t->words, -1 for pauses */
  char end;                                          /* pauses: '^' '$' 's' (spell) or the punctuation */
  int syl_from, syl_to, acc_from, acc_to, nsyl, nwords, ptype, yesno, pidx, nphr, acc_before, syl_left;
  double t0, t1, dur;
} q_t;

typedef struct { int code, ei, si[4]; } tframe_t;
typedef struct { int code, wi, ei, si[4]; } wframe_t;     /* a whole-word unit's frame */
typedef struct { char text[32]; int off, n; } wunit_t;    /* a whole-word unit */
typedef struct { int i0, u; } span_t;                     /* its first phone, the unit */
typedef struct { double t, c[NC], ei, w; int has_c, code; } kf_t;

struct sotto_tts {
  /* table */
  int kind, nst, f0;
  tframe_t *fr;
  int unit_off[NP * NP], unit_n[NP * NP], unit_split[NP * NP];   /* robot: index p; -1: none */
  /* prosody */
  const unsigned char *pros;
  unsigned pros_len;
  int med, pause[4], dur_tree, pitch_tree, trained;
  double rdur[NP][2];          /* the rule durations (s): stressed, unstressed */
  /* whole-word callsign units (words.stw), none when nwu is 0 */
  wunit_t *wu;
  wframe_t *wf;
  int nwu, wnst;
  /* per utterance */
  word_t *words;
  int nwords, cwords;
  phrase_t *phr;
  int nphr, cphr;
  q_t *seq;
  int nseq, cseq;
  kf_t *K;
  int nk, ck;
  int nfr, cfr;
  int *code, *wi, *ei;
  double *c;
  unsigned char *sf;
  int nsf;
  char *phones, *wtext;
  double *wt0;
  span_t *sp;                  /* the callsign elements spoken with a whole-word unit */
  int nsp, csp;
};

static int add_word(struct sotto_tts *t, const xw_t *x) {
  phs_t ph[MAXPH];
  int n = pronounce(x->text, ph);
  if (x->content == C_FUNC)
    for (int k = 0; k < n; k++) {
      ph[k].s = 0;
      if (ph[k].p == AH) ph[k].p = AX;
      if (ph[k].p == ER) ph[k].p = AXR;
    }
  if (!n) return 0;
  GROW(t->words, t->nwords, t->cwords);
  word_t *w = &t->words[t->nwords++];
  memcpy(w->text, x->text, sizeof w->text);
  memcpy(w->ph, ph, n * sizeof ph[0]);
  w->nph = n, w->content = x->content != C_FUNC, w->spell = x->content == C_SPELL;
  return 0;
}

static int close_phrase(struct sotto_tts *t, int w0, char end) {
  if (t->nwords == w0) return 0;
  GROW(t->phr, t->nphr, t->cphr);
  t->phr[t->nphr].w0 = w0, t->phr[t->nphr].nw = t->nwords - w0, t->phr[t->nphr].end = end;
  t->nphr++;
  return 0;
}

static int tok_char(int c) { return isalnum(c) || c == '.' || c == '/' || c == '\'' || c == '-'; }

/* frontend.text_to_phrases */
static int text_to_phrases(struct sotto_tts *t, const char *s) {
  t->nwords = t->nphr = 0;
  int w0 = 0;
  char prev[64] = "";
  int have_prev = 0;
  size_t i = 0, len = strlen(s);
  while (i < len) {
    unsigned char ch = (unsigned char)s[i];
    if (strchr(".,?!;:", ch) && ch) {
      char end = ch == ';' || ch == ':' ? ',' : (char)ch;
      if (close_phrase(t, w0, end)) return -1;
      w0 = t->nwords;
      i++;
      continue;
    }
    if (!isalnum(ch)) {
      i++;
      continue;
    }
    size_t j = i;
    while (j < len && tok_char((unsigned char)s[j])) j++;
    while (j > i + 1 && !isalnum((unsigned char)s[j - 1])) j--;
    char tok[64];
    size_t tl = j - i < 63 ? j - i : 63;
    memcpy(tok, s + i, tl);
    tok[tl] = 0;
    i = j;
    /* split on '-' unless the whole token is a callsign */
    char *parts[32];
    int np = 0;
    if (is_callsign(tok)) parts[np++] = tok;
    else {
      char *p = tok;
      parts[np++] = p;
      for (; *p; p++)
        if (*p == '-' && np < 32) *p = 0, parts[np++] = p + 1;
    }
    for (int k = 0; k < np; k++) {
      if (!*parts[k]) continue;
      xw_t x[MAXX];
      int nx = expand(parts[k], have_prev ? prev : NULL, x, 0);
      for (int m = 0; m < nx; m++)
        if (add_word(t, &x[m])) return -1;
      snprintf(prev, sizeof prev, "%s", parts[k]);
      have_prev = 1;
    }
  }
  return close_phrase(t, w0, '.');
}

/* ------------------------------------------------------------------ prosody (tts/prosody.py) */
static int add_q(struct sotto_tts *t, int p, int stress, int content, int word, int phrase, int spell, int gw, char end) {
  GROW(t->seq, t->nseq, t->cseq);
  q_t *q = &t->seq[t->nseq++];
  memset(q, 0, sizeof *q);
  q->p = p, q->stress = stress, q->content = content, q->word = word, q->phrase = phrase;
  q->spell = spell, q->gw = gw, q->end = end;
  q->acc_from = q->acc_to = -1;
  return 0;
}

static int ptype_of(char e) { return e == ',' ? 1 : e == '?' ? 2 : e == '!' ? 3 : 0; }

/* prosody.phone_sequence */
static int phone_sequence(struct sotto_tts *t) {
  t->nseq = 0;
  if (add_q(t, PAU, 0, 0, -1, -1, 0, -1, '^')) return -1;
  for (int j = 0; j < t->nphr; j++) {
    const phrase_t *ph = &t->phr[j];
    for (int wi = 0; wi < ph->nw; wi++) {
      const word_t *w = &t->words[ph->w0 + wi];
      for (int k = 0; k < w->nph; k++) {
        if (add_q(t, w->ph[k].p, w->ph[k].s, w->content, wi, j, w->spell, ph->w0 + wi, 0)) return -1;
        int last_of_word = k + 1 == w->nph, last_of_phrase = last_of_word && wi + 1 == ph->nw;
        if (last_of_word && w->spell && !last_of_phrase)
          if (add_q(t, PAU, 0, 0, -1, j, 1, -1, 's')) return -1;
      }
    }
    char end = j < t->nphr - 1 ? ph->end : '$';
    if (add_q(t, PAU, 0, 0, -1, -1, 0, -1, end)) return -1;
  }
  for (int j = 0; j < t->nphr; j++) {
    const phrase_t *ph = &t->phr[j];
    int nv = 0, na = 0, nsyl = 0, nacc = 0;
    for (int i = 0; i < t->nseq; i++) {
      q_t *q = &t->seq[i];
      if (q->phrase != j || q->p == PAU || !vowel(q->p)) continue;
      nsyl++;
      if (q->stress == 1 && q->content) nacc++;
    }
    int yesno = ph->end == '?' && ph->nw && in_list(AUX, t->words[ph->w0].text);
    int acc_idx[256], nai = 0;     /* vowel index of each accent */
    for (int i = 0; i < t->nseq; i++) {
      q_t *q = &t->seq[i];
      if (q->phrase != j || q->p == PAU || !vowel(q->p)) continue;
      q->syl_from = nv, q->syl_to = nsyl - 1 - nv;
      if (q->stress == 1 && q->content) {
        q->acc_from = na, q->acc_to = nacc - 1 - na;
        if (nai < 256) acc_idx[nai++] = nv;
        na++;
      }
      nv++;
    }
    nv = 0;
    for (int i = 0; i < t->nseq; i++) {
      q_t *q = &t->seq[i];
      if (q->phrase != j || q->p == PAU) continue;
      q->nsyl = nsyl, q->nwords = ph->nw, q->ptype = ptype_of(ph->end), q->yesno = yesno;
      q->pidx = j, q->nphr = t->nphr;
      int ab = 0;
      for (int a = 0; a < nai; a++) ab += acc_idx[a] < nv;
      q->acc_before = ab;
      if (vowel(q->p)) nv++;
      q->syl_left = nsyl - nv;
    }
  }
  return 0;
}

static int pclass(int p) {
  if (p == PAU) return 0;
  if (vowel(p)) return 1;
  if (stop(p)) return 2;
  if (fricative(p)) return 3;
  if (nasal(p)) return 4;
  if (liquid(p)) return 5;
  return 6;
}

/* prosody.features for phone i: dur[28], and pitch[20] for a vowel (returns 1) */
static int features(const struct sotto_tts *t, int i, int *d, int *pf) {
  const q_t *q = &t->seq[i];
  int pos = 0, n = 0, nwv = 0, first_v = -1, last_v = -1, sylw = 0;
  for (int k = 0; k < t->nseq; k++) {
    const q_t *r = &t->seq[k];
    if (r->phrase != q->phrase || r->word != q->word || r->p == PAU) continue;
    if (k == i) pos = n;
    if (vowel(r->p)) {
      if (first_v < 0) first_v = n;
      last_v = n;
      nwv++;
      if (k < i) sylw++;
    }
    n++;
  }
  int onset = (nwv && pos < first_v) ? 0 : (nwv && pos > last_v) ? 2 : 1;
  int prev = i ? t->seq[i - 1].p : PAU, nxt = i + 1 < t->nseq ? t->seq[i + 1].p : PAU, p = q->p;
  int reduced = p == AX || p == AXR || ((p == IH || p == UH || p == IY) && q->stress == 0);
  int fin = q->syl_left == 0 || (vowel(p) && q->syl_to == 0);
  int v[28] = {p, vowel(p), stop(p), fricative(p), nasal(p), liquid(p), affricate(p), voiced_c(p),
               diphthong(p), reduced, q->stress, q->content, pos, n - 1 - pos, n, nwv, fin,
               q->syl_left, q->nsyl - q->syl_left, q->ptype, pclass(prev), pclass(nxt), prev == PAU,
               nxt == PAU, voiced_c(nxt) || vowel(nxt), q->spell, onset, q->nwords};
  memcpy(d, v, sizeof v);
  if (!vowel(p)) return 0;
  int rel = (int)rint(16.0 * q->syl_from / (q->nsyl - 1 > 1 ? q->nsyl - 1 : 1));
  int w[20] = {q->stress, q->content, q->syl_from, q->syl_to, rel, q->ptype, q->word, q->nwords,
               q->acc_from, q->acc_to, q->acc_before, nwv, sylw, q->spell, q->pidx, q->nphr,
               q->pidx == q->nphr - 1, q->yesno, reduced, q->stress == 1 && q->content};
  memcpy(pf, w, sizeof w);
  return 1;
}

static int rd16(const unsigned char *b) { return (int16_t)(b[0] | b[1] << 8); }
static unsigned ru16(const unsigned char *b) { return b[0] | b[1] << 8; }

/* the end of a tree that starts at pos (prosody.Tree) */
static unsigned tree_end(const unsigned char *b, unsigned pos, int nout) {
  unsigned cnt = ru16(b + pos), p = pos + 2;
  for (unsigned n = 0; n < cnt; n++) p += b[p] == 0xFF ? 1 + 2 * nout : 5;
  return p;
}

/* prosody.Tree.predict: leaf values (1/256 units) */
static void tree_predict(const unsigned char *b, unsigned pos, const int *x, int nout, double *out) {
  unsigned p = pos + 2;
  while (b[p] != 0xFF) {
    int f = b[p], thr = rd16(b + p + 1);
    unsigned off = ru16(b + p + 3);
    p = x[f] * 16 <= thr ? p + 5 : p + off;
  }
  for (int k = 0; k < nout; k++) out[k] = rd16(b + p + 1 + 2 * k) / 256.0;
}

/* np.interp */
static double interp(double x, const double *xp, const double *fp, int n) {
  if (x < xp[0]) return fp[0];
  if (x >= xp[n - 1]) return fp[n - 1];
  int lo = 0, hi = n - 1;          /* largest j with xp[j] <= x */
  while (hi - lo > 1) {
    int m = (lo + hi) / 2;
    if (xp[m] <= x) lo = m;
    else hi = m;
  }
  double slope = (fp[lo + 1] - fp[lo]) / (xp[lo + 1] - xp[lo]);
  return slope * (x - xp[lo]) + fp[lo];
}

/* ------------------------------------------------------------------ unit table (tts/table.py) */
typedef struct { const unsigned char *b; unsigned n, p; } br_t;
static int get(br_t *r, int nb) {
  int v = 0;
  for (int k = 0; k < nb; k++, r->p++) {
    if ((r->p >> 3) >= r->n) return -1;
    v |= ((r->b[r->p >> 3] >> (r->p & 7)) & 1) << k;
  }
  return v;
}

static const int STAGE_BITS[4] = {9, 9, 8, 8};

static int read_table(struct sotto_tts *t, const unsigned char *b, unsigned n) {
  br_t r = {b, n, 0};
  if (n < 8 || memcmp(b, "STT1", 4)) return -1;
  r.p = 32;
  t->kind = get(&r, 8);
  int sb = get(&r, 8);
  t->nst = sb == 18 ? 2 : 4;
  t->f0 = get(&r, 16);
  for (int p = 0; p < NP; p++)
    for (int k = 0; k < 2; k++) t->rdur[p][k] = get(&r, 8) * 0.005;
  int cap = 0, nf = 0;
  for (int i = 0; i < NP * NP; i++) t->unit_off[i] = -1, t->unit_n[i] = 0;
  static unsigned char present[NP * NP];
  if (t->kind == 1)
    for (int i = 0; i < NP * NP; i++) present[i] = (unsigned char)get(&r, 1);
  int nu = t->kind == 0 ? NP : NP * NP;
  for (int u = 0; u < nu; u++) {
    int cnt, split = 0;
    if (t->kind == 0) cnt = get(&r, 3);
    else {
      if (!present[u]) continue;
      cnt = get(&r, 4);
      split = get(&r, 4);
    }
    if (cnt < 0) return -1;
    t->unit_off[u] = nf, t->unit_n[u] = cnt, t->unit_split[u] = split;
    for (int k = 0; k < cnt; k++) {
      GROW(t->fr, nf, cap);
      tframe_t *f = &t->fr[nf++];
      f->code = get(&r, 2);
      f->ei = get(&r, 5);
      for (int s = 0; s < 4; s++) f->si[s] = s < t->nst ? get(&r, STAGE_BITS[s]) : -1;
      if (f->si[t->nst - 1] < 0) return -1;
    }
  }
  return 0;
}

/* synth.shape_of: the sum of the frame's codebook stages, from the fixed-point codebook (8-bit
   values times a Q16 step per stage, as the K6's decoder reads it; within 0.002 dB of the
   float codebook tts/synth.py uses) */
static void shape_sum(int nst, const int *si, double *c) {
  int32_t acc[NC] = {0};
  int16_t buf[FX_CBW];
  for (int s = 0; s < nst; s++) {
    const int16_t *y = FX_CB_VEC(s, si[s], buf);
    for (int k = 0; k < NC; k++) acc[k] += (int32_t)FX_CB_VAL(y, k) * fx_cb_step[s];
  }
  for (int k = 0; k < NC; k++) c[k] = acc[k] / 65536.0;
}
static void shape_of(const struct sotto_tts *t, const tframe_t *f, double *c) { shape_sum(t->nst, f->si, c); }

/* table.read_words: the whole-word units ("STW1", shape bits, count, then per word its text
   (5-bit length, 7-bit characters), 7-bit frame count and frames of 2-bit code, 7-bit pitch
   index, 5-bit energy and the shape's stage indices) */
static int read_words(struct sotto_tts *t, const unsigned char *b, unsigned n) {
  br_t r = {b, n, 32};
  if (n < 6 || memcmp(b, "STW1", 4)) return -1;
  int sb = get(&r, 8), nw = get(&r, 8), cap = 0, nf = 0;
  t->wnst = sb == 18 ? 2 : 4;
  free(t->wu), free(t->wf);
  t->wu = calloc(nw > 0 ? nw : 1, sizeof *t->wu), t->wf = NULL, t->nwu = 0;
  if (!t->wu) return -1;
  for (int w = 0; w < nw; w++) {
    wunit_t *u = &t->wu[w];
    int len = get(&r, 5);
    if (len < 0 || len >= (int)sizeof u->text) return -1;
    for (int k = 0; k < len; k++) u->text[k] = (char)get(&r, 7);
    u->n = get(&r, 7), u->off = nf;
    if (u->n < 0) return -1;
    for (int k = 0; k < u->n; k++) {
      GROW(t->wf, nf, cap);
      wframe_t *f = &t->wf[nf++];
      f->code = get(&r, 2), f->wi = get(&r, 7), f->ei = get(&r, 5);
      for (int s = 0; s < 4; s++) f->si[s] = s < t->wnst ? get(&r, STAGE_BITS[s]) : -1;
      if (f->si[t->wnst - 1] < 0) return -1;
    }
  }
  t->nwu = nw;
  return 0;
}

int sotto_tts_set_words(struct sotto_tts *t, const unsigned char *stw, unsigned len) {
  if (!stw) return t->nwu = 0, 0;
  if (read_words(t, stw, len)) return t->nwu = 0, -1;
  return 0;
}

static const wunit_t *find_wunit(const struct sotto_tts *t, const char *text) {
  for (int k = 0; k < t->nwu; k++)
    if (!strcmp(t->wu[k].text, text)) return &t->wu[k];
  return NULL;
}

/* synth.fit_words: each callsign element that has a whole-word unit is stretched to the
   unit's length (its phones keep their proportions); returns the new total time */
static int fit_words(struct sotto_tts *t, double *total) {
  t->nsp = 0;
  for (int i = 0; t->nwu && i < t->nseq; i++) {
    const q_t *q = &t->seq[i];
    if (q->p == PAU || q->phrase < 0 || !q->spell) continue;
    if (i && t->seq[i - 1].p != PAU && t->seq[i - 1].gw == q->gw) continue;   /* not its first phone */
    const wunit_t *u = find_wunit(t, t->words[q->gw].text);
    if (!u || !u->n) continue;
    int j = i;
    double cur = 0;
    for (; j < t->nseq && t->seq[j].p != PAU && t->seq[j].gw == q->gw; j++) cur += t->seq[j].dur;
    for (int k = i; k < j; k++) t->seq[k].dur *= u->n * FRAME / cur;
    GROW(t->sp, t->nsp, t->csp);
    t->sp[t->nsp].i0 = i, t->sp[t->nsp++].u = (int)(u - t->wu);
  }
  double tm = 0;
  for (int i = 0; i < t->nseq; i++) {
    q_t *q = &t->seq[i];
    q->t0 = tm, q->t1 = tm + q->dur;
    tm += q->dur;
  }
  *total = tm;
  return 0;
}

/* synth.fr_of: seconds -> nearest frame, halves up (word starts often sit on exactly half
   a frame, where float noise would split round() from rint()) */
static int fr_of(double t) { return (int)floor(t / FRAME + 0.5 + 1e-6); }

/* synth.splice_words: the fitted elements' frames become the units' own (shape, energy,
   voicing, and pitch moved by the pitch setting); the pauses either side go silent */
static void splice_words(struct sotto_tts *t, double pitch) {
  int dw = (int)rint(127 * log10(pitch)), n = t->nfr;
  for (int s = 0; s < t->nsp; s++) {
    int i0 = t->sp[s].i0;
    const wunit_t *u = &t->wu[t->sp[s].u];
    int f0 = fr_of(t->seq[i0].t0);
    int lo = f0 - (i0 && t->seq[i0 - 1].p == PAU ? fr_of(t->seq[i0 - 1].dur) : 0);
    int i1 = i0;
    while (i1 < t->nseq && t->seq[i1].p != PAU) i1++;
    int hi = f0 + u->n + (i1 < t->nseq ? fr_of(t->seq[i1].dur) : 0);
    for (int f = lo < 0 ? 0 : lo; f < (hi < n ? hi : n); f++) t->ei[f] = 0, t->code[f] = 0;
    for (int k = 0; k < u->n; k++) {
      int f = f0 + k;
      if (f < 0 || f >= n) continue;
      const wframe_t *w = &t->wf[u->off + k];
      shape_sum(t->wnst, w->si, t->c + f * NC);
      t->ei[f] = w->ei, t->code[f] = w->code;
      int x = w->wi + dw;
      t->wi[f] = x < 0 ? 0 : x > 127 ? 127 : x;
    }
  }
}

/* ------------------------------------------------------------------ synthesis (tts/synth.py) */
static int add_key(struct sotto_tts *t, double tm, const tframe_t *f, double w) {
  GROW(t->K, t->nk, t->ck);
  kf_t *k = &t->K[t->nk++];
  k->t = tm, k->w = w, k->ei = f ? f->ei : 0, k->code = f ? f->code : 0;
  k->has_c = f && (t->kind == 0 || f->ei > 0);
  if (k->has_c) shape_of(t, f, k->c);
  return 0;
}

/* synth.keyframes_robot */
static int keyframes_robot(struct sotto_tts *t) {
  const double tau = 0.015;
  for (int i = 0; i < t->nseq; i++) {
    const q_t *q = &t->seq[i];
    if (q->p == PAU) {
      if (add_key(t, q->t0 + 0.01, NULL, 0) || add_key(t, q->t1 - 0.01, NULL, 0)) return -1;
      continue;
    }
    int n = t->unit_n[q->p];
    if (n <= 0) continue;
    double seg = q->dur / n, e = tau < seg / 4 ? tau : seg / 4;
    for (int j = 0; j < n; j++) {
      double a = q->t0 + seg * j;
      const tframe_t *f = &t->fr[t->unit_off[q->p] + j];
      if (add_key(t, a + e, f, 0) || add_key(t, a + seg - e, f, 0)) return -1;
    }
  }
  return 0;
}

static const char *const SUB_FROM[] = {"AXR", "ER", "AX", "AH", "ZH", "NG", "OY", "UH", "TH", "DH", "IH", "IY",
                                       "EH", "AE", "AA", "AO", "UW", "Y", "W", "HH"};
static const char *const SUB_TO[] = {"ER", "AXR", "AH", "AX", "SH", "N", "AO", "UW", "F", "V", "IY", "IH",
                                     "AE", "EH", "AO", "AA", "UH", "IY", "UW", "PAU"};
static int sub_of(int p) {
  for (int i = 0; i < 20; i++)
    if (!strcmp(PH[p], SUB_FROM[i])) return phone_id(SUB_TO[i], (int)strlen(SUB_TO[i]));
  return p;
}

/* synth.find_unit: frames (as table indices, -1 ends) of a-b or its stand-ins; returns split */
static int find_unit(const struct sotto_tts *t, int a, int b, int *fr, int *n, int *sub) {
  int xs[4] = {a, sub_of(a), a, sub_of(a)}, ys[4] = {b, b, sub_of(b), sub_of(b)};
  for (int k = 0; k < 4; k++) {
    int u = xs[k] * NP + ys[k];
    if (t->unit_off[u] >= 0) {
      *n = t->unit_n[u];
      for (int j = 0; j < *n; j++) fr[j] = t->unit_off[u] + j;
      *sub = k > 0 && (xs[k] != a || ys[k] != b);
      return t->unit_split[u];
    }
  }
  int order[3 + NP], no = 0;
  order[no++] = AX, order[no++] = AH, order[no++] = PAU;
  for (int z = 0; z < NP; z++) order[no++] = z;
  int L = -1, R = -1;
  for (int k = 0; k < no && L < 0; k++)
    if (t->unit_off[a * NP + order[k]] >= 0) L = a * NP + order[k];
  for (int k = 0; k < no && R < 0; k++)
    if (t->unit_off[order[k] * NP + b] >= 0) R = order[k] * NP + b;
  *n = 0;
  if (L >= 0)
    for (int j = 0; j < t->unit_split[L]; j++) fr[(*n)++] = t->unit_off[L] + j;
  if (R >= 0)
    for (int j = t->unit_split[R]; j < t->unit_n[R]; j++) fr[(*n)++] = t->unit_off[R] + j;
  *sub = 1;
  return L >= 0 ? t->unit_split[L] : 0;
}

/* synth.keyframes_diphone: parts[i] = keyframes [lo, mid) left half, [mid, hi) right half */
static int keyframes_diphone(struct sotto_tts *t, int *subs) {
  int nu = t->nseq - 1, *lo = malloc((nu + 1) * sizeof *lo), *mid = malloc((nu + 1) * sizeof *mid);
  if (!lo || !mid) return free(lo), free(mid), -1;
  *subs = 0;
  for (int i = 0; i < nu; i++) {
    const q_t *qa = &t->seq[i], *qb = &t->seq[i + 1];
    int fr[32], n, sub, split = find_unit(t, qa->p, qb->p, fr, &n, &sub);
    *subs += sub;
    double ma = 0.5 * (qa->t0 + qa->t1), mb = 0.5 * (qb->t0 + qb->t1);
    lo[i] = t->nk;
    for (int side = 0; side < 2; side++) {
      int j0 = side ? split : 0, j1 = side ? n : split, m = j1 - j0;
      double t0 = side ? qb->t0 : ma, t1 = side ? mb : qa->t1;
      if (side) mid[i] = t->nk;
      for (int j = 0; j < m; j++)
        if (add_key(t, t0 + (t1 - t0) * (j + 0.5) / m, &t->fr[fr[j0 + j]], (j + 0.5) / m))
          return free(lo), free(mid), -1;
    }
  }
  lo[nu] = t->nk;
  const double smooth = 0.5;
  for (int i = 1; i < t->nseq - 1; i++) {
    if (t->seq[i].p == PAU) continue;
    int r0 = mid[i - 1], r1 = lo[i], l0 = lo[i], l1 = mid[i];   /* R: unit i-1's right, L: unit i's left */
    if (r1 <= r0 || l1 <= l0) continue;
    kf_t *a = &t->K[r1 - 1], *b = &t->K[l0];
    if (a->has_c && b->has_c) {
      double d[NC];
      for (int k = 0; k < NC; k++) d[k] = smooth * 0.5 * (b->c[k] - a->c[k]);
      for (int x = r0; x < r1; x++)
        if (t->K[x].has_c)
          for (int k = 0; k < NC; k++) t->K[x].c[k] = t->K[x].c[k] + d[k] * t->K[x].w;
      for (int x = l0; x < l1; x++)
        if (t->K[x].has_c)
          for (int k = 0; k < NC; k++) t->K[x].c[k] = t->K[x].c[k] - d[k] * (1 - t->K[x].w);
    }
    if (a->ei > 0 && b->ei > 0) {
      double de = smooth * 0.5 * (b->ei - a->ei);
      for (int x = r0; x < r1; x++)
        if (t->K[x].ei > 0) t->K[x].ei += de * t->K[x].w;
      for (int x = l0; x < l1; x++)
        if (t->K[x].ei > 0) t->K[x].ei -= de * (1 - t->K[x].w);
    }
  }
  free(lo), free(mid);
  return 0;
}

static int key_cmp(const void *a, const void *b) {
  const kf_t *x = a, *y = b;
  if (x->t != y->t) return x->t < y->t ? -1 : 1;
  return x->w < y->w ? -1 : x->w > y->w;     /* never reached in practice; see render */
}

/* synth.render + synth.fix_voicing */
static int render(struct sotto_tts *t, int n) {
  /* stable sort by time (Python's sorted): insertion sort, the keys are nearly in order */
  for (int i = 1; i < t->nk; i++) {
    kf_t k = t->K[i];
    int j = i;
    while (j > 0 && t->K[j - 1].t > k.t) t->K[j] = t->K[j - 1], j--;
    t->K[j] = k;
  }
  (void)key_cmp;
  int nk = t->nk;
  double *tk = malloc(nk * sizeof *tk), *col = malloc(nk * sizeof *col), *E = malloc(nk * sizeof *E);
  if (!tk || !col || !E) return free(tk), free(col), free(E), -1;
  const double *last = NULL;
  static const double zero[NC];
  for (int i = 0; i < nk; i++)
    if (t->K[i].has_c) {
      last = t->K[i].c;
      break;
    }
  if (!last) last = zero;
  for (int i = 0; i < nk; i++) {
    if (!t->K[i].has_c) memcpy(t->K[i].c, last, sizeof t->K[i].c), t->K[i].has_c = 2;
    else last = t->K[i].c;
    tk[i] = t->K[i].t, E[i] = t->K[i].ei;
  }
  for (int f = 0; f < n; f++) {
    double tc = f * FRAME + 0.5 * FRAME, best = 1e30;
    int near = 0;
    for (int i = 0; i < nk; i++) {
      double d = fabs(tc - tk[i]);
      if (d < best) best = d, near = i;
    }
    t->code[f] = t->K[near].code;
    t->ei[f] = (int)rint(interp(tc, tk, E, nk));
  }
  for (int k = 0; k < NC; k++) {
    for (int i = 0; i < nk; i++) col[i] = t->K[i].c[k];
    for (int f = 0; f < n; f++) t->c[f * NC + k] = interp(f * FRAME + 0.5 * FRAME, tk, col, nk);
  }
  free(tk), free(col), free(E);
  for (int f = 0; f < n; f++)
    if (t->ei[f] == 0) t->code[f] = 0;
  for (int f = 0; f < n; f++)
    if (t->code[f] == 3) {
      int prev = f ? t->code[f - 1] : 0, nxt = f + 1 < n ? t->code[f + 1] : 0;
      if (prev != 0 && nxt != 0) t->code[f] = 2;
    }
  for (int f = 0; f < n; f++) t->ei[f] = t->ei[f] < 0 ? 0 : t->ei[f] > 31 ? 31 : t->ei[f];
  return 0;
}

/* ------------------------------------------------------------------ rule prosody (synth.py) */
#define SLOW 1.15
#define SPELL_GAP 0.2   /* s between callsign elements (synth.SPELL_GAP) */

/* synth.phone_plan's durations, on the phone sequence (the same phones and pauses); returns
   the end time */
static double rule_durations(struct sotto_tts *t, double rate) {
  double tm = 0;
  for (int j = 0; j < t->nphr; j++) {
    int nk = 0, last_v = -1;              /* the phrase's last vowel, counting its phones */
    for (int i = 0; i < t->nseq; i++) {
      const q_t *q = &t->seq[i];
      if (q->phrase != j || q->p == PAU) continue;
      if (vowel(q->p)) last_v = nk;
      nk++;
    }
    if (last_v < 0) last_v = nk;
    int k = 0;
    for (int i = 0; i < t->nseq; i++) {
      q_t *q = &t->seq[i];
      if (q->phrase != j) continue;
      if (q->p == PAU) {                  /* a callsign's gap (synth.SPELL_GAP) */
        q->dur = SPELL_GAP / rate;
        continue;
      }
      double du = t->rdur[q->p][q->stress > 0 ? 0 : 1];
      if (!q->content) du *= 0.85;
      if (k >= last_v) du *= 1.35;
      q->dur = SLOW * du / rate;
      k++;
    }
  }
  for (int i = 0; i < t->nseq; i++) {
    q_t *q = &t->seq[i];
    if (q->phrase < 0)                    /* the start, and each phrase's closing pause */
      q->dur = q->end == '^' ? 0.12 : q->end == '$' ? 0.2 : q->end == ',' ? 0.22 : 0.4;
    if (q->dur < 0.03) q->dur = 0.03;
    q->t0 = tm, q->t1 = tm + q->dur;
    tm += q->dur;
  }
  return tm;
}

typedef struct { double t, v; } pt_t;
static int add_pt(pt_t **P, int *n, int *cap, double tm, double v) {
  GROW(*P, *n, *cap);
  (*P)[*n].t = tm, (*P)[(*n)++].v = v;
  return 0;
}

/* synth.f0_track: a falling baseline per phrase, a peak on each accent, and the phrase's
   ending (fall, comma rise or yes/no question rise); sets t->wi */
static int rule_pitch(struct sotto_tts *t, int n, double f0) {
  pt_t *P = NULL;
  int np = 0, cap = 0;
  for (int j = 0; j < t->nphr; j++) {
    int first = -1, last = -1;
    for (int i = 0; i < t->nseq; i++)
      if (t->seq[i].phrase == j) {
        if (first < 0) first = i;
        last = i;
      }
    if (first < 0) continue;
    double t0 = t->seq[first].t0, t1 = t->seq[last].t1, span = t1 - t0 > 0.2 ? t1 - t0 : 0.2;
#define BASE(x) (f0 * (1.02 - 0.15 * ((x) - t0) / span))
    if (add_pt(&P, &np, &cap, t0, BASE(t0))) return free(P), -1;
    int k = 0;
    for (int i = first; i <= last; i++) {
      const q_t *q = &t->seq[i];
      if (q->phrase != j || q->p == PAU || !vowel(q->p) || q->stress != 1 || !q->content) continue;
      double pk = f0 * (1.32 - 0.07 * k > 1.12 ? 1.32 - 0.07 * k : 1.12);
      if (add_pt(&P, &np, &cap, q->t0, BASE(q->t0) * 1.02) ||
          add_pt(&P, &np, &cap, 0.5 * (q->t0 + q->t1), pk * (1.0 - 0.15 * (q->t0 - t0) / span)))
        return free(P), -1;
      k++;
    }
#undef BASE
    const phrase_t *ph = &t->phr[j];
    int yesno = ph->end == '?' && ph->nw && in_list(AUX, t->words[ph->w0].text);
    if (add_pt(&P, &np, &cap, t1, f0 * (ph->end == ',' ? 1.1 : yesno ? 1.5 : 0.76))) return free(P), -1;
  }
  /* pts.sort(): by time, then value */
  for (int i = 1; i < np; i++) {
    pt_t x = P[i];
    int j = i;
    while (j > 0 && (P[j - 1].t > x.t || (P[j - 1].t == x.t && P[j - 1].v > x.v))) P[j] = P[j - 1], j--;
    P[j] = x;
  }
  double *tt = malloc((np + 1) * sizeof *tt), *lf = malloc((np + 1) * sizeof *lf);
  if (!tt || !lf) return free(P), free(tt), free(lf), -1;
  for (int i = 0; i < np; i++) tt[i] = P[i].t, lf[i] = log(P[i].v);
  double lw0 = log(2 * PI_D / 160), lw1 = log(2 * PI_D / 16);
  for (int f = 0; f < n; f++) {
    double hz = np ? exp(interp(f * FRAME, tt, lf, np)) : f0;
    double wo = 2 * PI_D * hz / 8000;
    double x = rint((log(wo) - lw0) / (lw1 - lw0) * 127);
    t->wi[f] = x < 0 ? 0 : x > 127 ? 127 : (int)x;
  }
  free(P), free(tt), free(lf);
  return 0;
}

void sotto_tts_trained(struct sotto_tts *t, int on) { t->trained = on; }

/* ------------------------------------------------------------------ API */
struct sotto_tts *sotto_tts_create(const unsigned char *table, unsigned table_len,
                                   const unsigned char *prosody, unsigned prosody_len) {
  if (parse_rules() || parse_lexicon()) return NULL;
  struct sotto_tts *t = calloc(1, sizeof *t);
  if (!t) return NULL;
  if (read_table(t, table, table_len) || (prosody && (prosody_len < 10 || memcmp(prosody, "STP1", 4)))) {
    sotto_tts_destroy(t);
    return NULL;
  }
  if (!prosody) return t;
  t->pros = prosody, t->pros_len = prosody_len;
  t->med = (int)ru16(prosody + 4);
  for (int k = 0; k < 4; k++) t->pause[k] = prosody[6 + k];
  t->dur_tree = 10;
  t->pitch_tree = (int)tree_end(prosody, 10, 1);
  return t;
}

void sotto_tts_destroy(struct sotto_tts *t) {
  if (!t) return;
  free(t->fr), free(t->words), free(t->phr), free(t->seq), free(t->K);
  free(t->code), free(t->wi), free(t->ei), free(t->c), free(t->sf), free(t->phones);
  free(t->wtext), free(t->wt0), free(t->wu), free(t->wf), free(t->sp);
  free(t);
}

int sotto_tts_say(struct sotto_tts *t, const char *text, double rate, double pitch) {
  t->nsf = 0;
  if (text_to_phrases(t, text) || phone_sequence(t)) return -1;
  int d[28], pf[20], trees = t->trained && t->pros;
  double tm = 0, v[3];
  if (!trees) tm = rule_durations(t, rate);
  /* durations: prosody.Model.time */
  for (int i = 0; trees && i < t->nseq; i++) {
    q_t *q = &t->seq[i];
    double du;
    if (q->p == PAU) {
      char e = q->end;
      du = e == '^' ? 0.15 : e == '$' ? 0.2 : e == 's' ? 0.08 : t->pause[ptype_of(e)] * 0.005;
    } else {
      features(t, i, d, pf);
      tree_predict(t->pros, t->dur_tree, d, 1, v);
      du = exp(v[0]);
    }
    du = du / rate;
    if (du < 0.02) du = 0.02;
    q->dur = du, q->t0 = tm, q->t1 = tm + du;
    tm += du;
  }
  if (fit_words(t, &tm)) return -1;
  int n = (int)ceil(tm / FRAME);
  n += n % 2;
  free(t->code), free(t->wi), free(t->ei), free(t->c);
  t->code = malloc(n * sizeof(int)), t->wi = malloc(n * sizeof(int)), t->ei = malloc(n * sizeof(int));
  t->c = malloc(n * NC * sizeof(double));
  if (!t->code || !t->wi || !t->ei || !t->c) return -1;
  t->nfr = n;
  /* keyframes and frames */
  t->nk = 0;
  int subs = 0;
  if ((t->kind == 0 ? keyframes_robot(t) : keyframes_diphone(t, &subs)) || render(t, n)) return -1;
  if (!trees) {
    if (rule_pitch(t, n, t->f0 * pitch)) return -1;
    goto code;
  }
  /* pitch: prosody.Model.f0_track */
  int nt = 0, *tq = malloc((3 * t->nseq + 1) * sizeof *tq);
  double *tt = malloc((3 * t->nseq + 1) * sizeof *tt), *lf = malloc((3 * t->nseq + 1) * sizeof *lf);
  if (!tt || !lf || !tq) return free(tt), free(lf), free(tq), -1;
  for (int i = 0; i < t->nseq; i++) {
    const q_t *q = &t->seq[i];
    if (q->p == PAU || !features(t, i, d, pf)) continue;
    tree_predict(t->pros, t->pitch_tree, pf, 3, v);
    static const double X[3] = {0.2, 0.5, 0.8};
    for (int k = 0; k < 3; k++) tt[nt] = q->t0 + X[k] * (q->t1 - q->t0), lf[nt] = v[k], tq[nt++] = i;
  }
  /* a yes/no question rises from its last accent's middle to its end (Model.f0_track) */
  for (int j = 0; j < t->nphr; j++) {
    int first = -1, lastk = -1, lacc = -1;
    for (int k = 0; k < nt; k++) {
      const q_t *q = &t->seq[tq[k]];
      if (q->phrase != j || !q->yesno) continue;
      if (first < 0) first = k;
      lastk = k;
      if (q->stress == 1 && q->content) lacc = k;
    }
    if (first < 0) continue;
    int k0 = lacc >= 0 ? lacc - 1 : first;
    double ta = tt[k0], te = tt[lastk];
    for (int k = first; k <= lastk; k++)
      if (t->seq[tq[k]].phrase == j && tt[k] > ta && te > ta) lf[k] += YESNO_RISE * (tt[k] - ta) / (te - ta);
  }
  free(tq);
  double base = log(t->med * pitch), lw0 = log(2 * PI_D / 160), lw1 = log(2 * PI_D / 16);
  for (int f = 0; f < n; f++) {
    double hz = exp(base + (nt ? interp(f * FRAME, tt, lf, nt) : 0));
    double wo = 2 * PI_D * hz / 8000;
    double x = rint((log(wo) - lw0) / (lw1 - lw0) * 127);
    t->wi[f] = x < 0 ? 0 : x > 127 ? 127 : (int)x;
  }
  free(tt), free(lf);
code:
  splice_words(t, pitch);
  /* code: the K6's fixed-point sotto 1200 coder */
  struct sotto_lr_enc *e = sotto_lr_enc_create_frames();
  free(t->sf);
  t->sf = malloc((n / 2 + 4) * SOTTO_BYTES_PER_FRAME);
  if (!e || !t->sf) return free(e), -1;
  for (int f = 0; f < n; f++) {
    fx_fparams_t p;
    p.code = (int16_t)t->code[f], p.wi = (int16_t)t->wi[f], p.ei = (int16_t)t->ei[f];
    for (int k = 0; k < FX_NC; k++) p.c[k] = (int32_t)lrint(t->c[f * NC + k] * 65536.0);
    sotto_lr_enc_push(e, &p);
    while (sotto_lr_enc_pop(e, t->sf + t->nsf * SOTTO_BYTES_PER_FRAME)) t->nsf++;
  }
  sotto_lr_enc_end(e);
  while (t->nsf < n / 2 + 4 && sotto_lr_enc_pop(e, t->sf + t->nsf * SOTTO_BYTES_PER_FRAME)) t->nsf++;
  free(e);
  /* the report */
  free(t->phones), free(t->wtext), free(t->wt0);
  t->phones = malloc(t->nseq * 5 + 1);
  t->wtext = malloc(t->nwords * 65 + 1);
  t->wt0 = malloc((t->nwords + 1) * sizeof *t->wt0);
  if (!t->phones || !t->wtext || !t->wt0) return -1;
  char *o = t->phones;
  for (int i = 0; i < t->nseq; i++) {
    const q_t *q = &t->seq[i];
    o += sprintf(o, i ? " %s" : "%s", PH[q->p]);
    if (q->stress) o += sprintf(o, "%d", q->stress);
  }
  *o = 0;
  o = t->wtext;
  *o = 0;
  for (int w = 0; w < t->nwords; w++) o += sprintf(o, w ? " %s" : "%s", t->words[w].text), t->wt0[w] = -1;
  for (int i = t->nseq - 1; i >= 0; i--)
    if (t->seq[i].gw >= 0) t->wt0[t->seq[i].gw] = t->seq[i].t0;
  return t->nsf;
}

const unsigned char *sotto_tts_superframes(const struct sotto_tts *t) { return t->sf; }
const char *sotto_tts_phones(const struct sotto_tts *t) { return t->phones; }
const char *sotto_tts_words(const struct sotto_tts *t) { return t->wtext; }
int sotto_tts_word_times(const struct sotto_tts *t, const double **t0) {
  *t0 = t->wt0;
  return t->nwords;
}
int sotto_tts_frames(const struct sotto_tts *t, const int **code, const int **wi, const int **ei, const double **c) {
  *code = t->code, *wi = t->wi, *ei = t->ei, *c = t->c;
  return t->nfr;
}
