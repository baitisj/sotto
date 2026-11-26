/* Harmonic phase watermark for FM voice: C port of watermark/harmonic.py, fec.py and fmchan.py.
 *
 * The sender follows the talker's pitch and turns the phase of the odd harmonics in the data
 * band so that, for each odd k, D_k = arg(z_{k+1} z_{k-1} / z_k^2) reads 0 (bit 0) or pi
 * (bit 1) for a 32 ms slot. The receiver tracks the pitch of what it hears, reads D_k back,
 * finds the slot timing and the channel's phase bend blindly, and Viterbi-decodes a repeating
 * 56-bit ID frame (base-40 callsign, one code byte, CRC-16; K=7 rate 1/2).
 *
 * Audio is 8 kHz float, speech near -26 dBFS (full scale 1.0). Pitch tracks are per sample:
 * f0 in Hz and a voiced flag. wm_track.c makes them with sotto's encoder pitch tracker;
 * without it (selftest), pass any track, as watermark/selftest.py does.
 * SPDX-License-Identifier: MIT */
#ifndef WM_H
#define WM_H

#define WM_FS 8000
#define WM_SLOT 256           /* samples per slot (32 ms) */
#define WM_MAXSUB 4
#define WM_MSGBITS 56
#define WM_NCODE 124          /* coded bits: 2 * (56 + 6) */

typedef struct {
  double lo, hi;              /* data band, Hz (500, 2600) */
  int nsub;                   /* sub-bands = bits per voiced slot (4) */
  double strength;            /* fraction of the full rotation (1) */
} wm_params;

void wm_default_params(wm_params *p);

/* ---- message ---- */
typedef struct {
  unsigned char msg[WM_MSGBITS];
  unsigned char cw[WM_NCODE];    /* coded and whitened */
  int nsub;
} wm_code;

/* call: up to 6 characters of " A-Z0-9-/." (base 40); code: 0..255 */
void wm_code_init(wm_code *c, const char *call, int code, int nsub);
void wm_bits_for_slot(const wm_code *c, int j, unsigned char *bits);
/* grid position q (mod WM_NCODE) -> coded bit index */
int wm_perm(int q);

/* ---- pitch (wm_track.c, needs libsotto) ---- */
/* the receiver's track: f0 (Hz) and voiced per sample */
void wm_pitch_track(const double *x, int n, double *f0, unsigned char *v);
/* the sender's track: the 300-3000 Hz audio's pitch, voiced where it agrees within 5% with
   the full-band pitch (harmonic.tx_track) */
void wm_tx_track(const double *x, int n, double *f0, unsigned char *v);

/* ---- sender ---- */
/* y = marked x; used[slot] = 1 where the slot was marked (n / WM_SLOT slots). Returns the
   slot count. */
int wm_embed(const wm_params *p, const double *x, int n, const double *f0, const unsigned char *v,
             const wm_code *c, double *y, unsigned char *used);

/* ---- receiver ---- */
typedef struct wm_rx wm_rx;

wm_rx *wm_rx_create(const wm_params *p, const double *y, int n, const double *f0,
                    const unsigned char *v);
void wm_rx_destroy(wm_rx *r);

/* Blind read of the audio up to sample `upto` (n for all of it): timing, equaliser and
   per-sub-band polarity. R gets (slots x nsub) real soft values, positive = bit 0, zero where
   unvoiced. Returns the slot count; *offset gets the grid offset in samples. */
int wm_rx_read(wm_rx *r, int upto, double *R, int *offset);
int wm_rx_max_slots(const wm_rx *r);

typedef struct {
  char call[8];
  int code, start;
  double quality;
} wm_frame;

/* Try every codeword start; 1 and *f for the first frame that passes the CRC with at least
   80% of coded bits heard and a soft agreement of 0.9 or more (fec.Code.decode). cover gets
   the share of coded bits heard. ring (WM_NCODE, may be NULL) gets the soft sum per grid
   position mod WM_NCODE. */
int wm_decode(const double *R, int nslots, int nsub, wm_frame *f, double *cover, double *ring);

/* ---- channel model (fmchan.py) ---- */
enum { WM_CH_CLEAN, WM_CH_BANDPASS, WM_CH_SIMPLEX, WM_CH_REPEATER };
void wm_channel(const double *x, int n, int kind, double cnr_in, double cnr_out, double drive_db,
                unsigned seed, double *y);

#endif
