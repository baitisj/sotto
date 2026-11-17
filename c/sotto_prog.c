/* Progressive sotto 2400: decoding a clip of which only some fields have arrived
 * (docs/sotto-progressive.md section 4, the C side of sim/sotto_prog.py's _partial_2400 and
 * decode16). The full decode needs none of this: once every field is in, the frames are the
 * streamed frames and the normal decoder plays them.
 *
 * known[f] has bit k set when field k of frame f's 2400 layout has arrived, k = 0..6 for
 * c (voicing, 2 bits), w (pitch, 7), e (energy, 5), s0 (9), s1 (9), s2 (8), s3 (8).
 * The fill looks at the whole clip (a missing field takes its nearest neighbours on both
 * sides), so it runs once over the clip, then the frames go through the decoder one by one.
 * SPDX-License-Identifier: MIT */
#include <string.h>
#include "sotto_prog.h"
#include "sotto_codebook.h"

#define NC (SOTTO_K - 1)

/* sim/data/prog_prior.npz: the shape (DCT coefficients 1..19, dB) for each voicing code when
   no frame of the clip has a shape yet; trained by tools/prog_race.py --train-prior on the six
   Codec 2 reference clips (none in the test set). float32 values, as the npz holds them. */
static const float prior[4][NC] = {
  {12.8611994f, -37.8903236f, 8.30507565f, -9.51096821f, 1.64120305f, -1.891536f, 0.638351738f,
   -0.786534607f, 0.555768728f, 0.783077478f, 0.197042823f, -0.528166234f, 0.0847656131f,
   0.422514021f, -0.481723845f, 0.613033414f, -0.705613077f, 0.524654567f, 0.0693129003f},
  {38.8804359f, 5.42414665f, 9.04459476f, -5.77531767f, -0.446451664f, -1.42193449f, -1.06093216f,
   -0.635047555f, 0.429127067f, -1.55766439f, 2.16308618f, -0.987713337f, 0.326690108f,
   0.548930168f, 0.403979093f, -0.498588562f, 0.248383194f, -0.0896762758f, 0.021812465f},
  {32.110569f, 1.86447394f, 7.15452337f, -2.23252702f, 0.107472993f, -2.08822274f, -0.0932262763f,
   -0.141888827f, 0.0979351029f, -0.23438625f, 1.08346665f, -0.938428283f, 0.829724133f,
   -0.137926564f, 0.0974483117f, -0.165672407f, 0.0743731186f, -0.10476166f, -9.16680365e-05f},
  {28.477066f, 0.603475094f, 7.6167779f, -3.20132113f, -0.517712533f, -1.91492581f, 0.364020258f,
   -0.492767185f, 0.839521468f, -0.320567578f, 1.43848693f, -0.824181497f, 0.537601769f,
   0.0409920551f, 0.0651758835f, -0.393016428f, 0.0622722097f, -0.118908003f, 0.147292569f},
};

static const int field_pos[SOTTO_PROG_NFIELDS] = {0, 2, 9, 14, 23, 32, 40};
static const int field_bits[SOTTO_PROG_NFIELDS] = {2, 7, 5, 9, 9, 8, 8};

static int get_field(const unsigned char *b, int pos, int w) {
  int v = 0;
  for (int i = 0; i < w; i++, pos++) v = (v << 1) | ((b[pos >> 3] >> (7 - (pos & 7))) & 1);
  return v;
}

static void put_field(unsigned char *b, int pos, int w, int v) {
  for (int i = 0; i < w; i++, pos++) {
    int bit = (v >> (w - 1 - i)) & 1;
    if (bit) b[pos >> 3] |= (unsigned char)(0x80 >> (pos & 7));
    else b[pos >> 3] &= (unsigned char)~(0x80 >> (pos & 7));
  }
}

const int *sotto_prog_field_bits(void) { return field_bits; }

void sotto_prog_prior(int code, double c[SOTTO_K - 1]) {
  for (int k = 0; k < NC; k++) c[k] = prior[code & 3][k];
}

#define VPE (SOTTO_PROG_C | SOTTO_PROG_W | SOTTO_PROG_E)

void sotto_prog_fill2400(const unsigned char *bits, const unsigned char *known, int n, sotto_fparams_t *p,
                         unsigned char *rows, unsigned char *sgood) {
  /* the fields as received (an unknown field's bits are whatever the buffer holds) */
  int nv = 0, ns = 0;
  for (int f = 0; f < n; f++) {
    const unsigned char *b = bits + SOTTO_BYTES_PER_FRAME * f;
    p[f].code = get_field(b, 0, 2);
    p[f].wi = get_field(b, 2, 7);
    p[f].ei = get_field(b, 9, 5);
    sgood[f] = (known[f] & VPE) == VPE;
    nv += sgood[f];
    ns += (known[f] & SOTTO_PROG_S0) != 0;
  }
  /* voicing, pitch, energy: sotto 1200's B rule from the nearest frames that have them
     (sotto_prog._fill_vpe with hiss = True). prev / next: nearest known frame before / after. */
  if (nv == 0) {
    for (int f = 0; f < n; f++) p[f].code = 0, p[f].wi = 0, p[f].ei = 0;
  } else {
    int a = -1;
    for (int f = 0; f < n; f++) {
      if (sgood[f]) { a = f; continue; }
      int b = -1;
      for (int j = f + 1; j < n; j++)
        if (sgood[j]) { b = j; break; }
      int A = a >= 0 ? a : b, B = b >= 0 ? b : a;
      int va = p[A].code != 0, vb = p[B].code != 0;
      if (va && vb) p[f].wi = (p[A].wi + p[B].wi + 1) >> 1;
      else p[f].wi = (va || !vb) ? p[A].wi : p[B].wi;
      p[f].ei = (p[A].ei + p[B].ei + 1) >> 1;
      int c = (f - A) <= (B - f) ? p[A].code : p[B].code;
      p[f].code = c == 3 ? 2 : c;
      if (p[f].code == 0) {
        /* an unvoiced frame's pitch field is its hiss index: copy the nearest known UU
           frame's (the earlier one on a tie), never average two */
        int best = -1;
        for (int d = 1; d < n && best < 0; d++) {
          if (f - d >= 0 && sgood[f - d] && p[f - d].code == 0) best = f - d;
          else if (f + d < n && sgood[f + d] && p[f + d].code == 0) best = f + d;
        }
        if (best >= 0) p[f].wi = p[best].wi;
      }
    }
  }
  /* shape: the sum of the stages that have arrived, when stage 1 is among them */
  for (int f = 0; f < n; f++) {
    for (int k = 0; k < NC; k++) p[f].c[k] = 0;
    if (!(known[f] & SOTTO_PROG_S0)) continue;
    const unsigned char *b = bits + SOTTO_BYTES_PER_FRAME * f;
    int pos = 14;
    for (int s = 0; s < sotto_cb_stages; s++) {
      int idx = get_field(b, pos, sotto_cb_bits[s]);
      pos += sotto_cb_bits[s];
      if (!(known[f] & (SOTTO_PROG_S0 << s))) continue;
      const float *y = sotto_cb[s] + idx * NC;
      for (int k = 0; k < NC; k++) p[f].c[k] += y[k];
    }
  }
  /* no shape: linear in time between the nearest frames with one, held at the ends
     (np.interp), or the prior for the frame's voicing code when no frame has one */
  if (ns == 0) {
    for (int f = 0; f < n; f++) sotto_prog_prior(p[f].code, p[f].c);
  } else {
    int a = -1;
    for (int f = 0; f < n; f++) {
      if (known[f] & SOTTO_PROG_S0) { a = f; continue; }
      int b = -1;
      for (int j = f + 1; j < n; j++)
        if (known[j] & SOTTO_PROG_S0) { b = j; break; }
      if (a < 0) memcpy(p[f].c, p[b].c, sizeof p[f].c);
      else if (b < 0) memcpy(p[f].c, p[a].c, sizeof p[f].c);
      else {
        double t = (double)(f - a) / (b - a);
        for (int k = 0; k < NC; k++) p[f].c[k] = p[a].c[k] + t * (p[b].c[k] - p[a].c[k]);
      }
    }
  }
  /* the rows the hiss layer reads: the received bits with the filled voicing and pitch (a UU
     frame's hiss index and side-channel bit live in its pitch field) */
  for (int f = 0; f < n; f++) {
    unsigned char *r = rows + SOTTO_BYTES_PER_FRAME * f;
    memcpy(r, bits + SOTTO_BYTES_PER_FRAME * f, SOTTO_BYTES_PER_FRAME);
    put_field(r, field_pos[0], 2, p[f].code);
    put_field(r, field_pos[1], 7, p[f].wi);
  }
}
