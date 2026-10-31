/* sotto: 2400 bit/s speech codec, 48 bits per 20 ms frame.
 *
 * C port of sotto v3.5 (sim/vocoder_lab.py SottoV35) with the real-time pitch tracker
 * (fixed-lag Viterbi, 80 ms look-ahead). Analysis and synthesis reuse Codec 2's sinusoidal
 * model (libcodec2, LGPL-2.1, linked); this code is MIT.
 *
 * Frame: voicing 2 | Wo 7 | energy 5 | shape 12+11+11, MSB first, packed into 6 bytes.
 *
 * Encoder: feed 160 samples (20 ms, 8 kHz, 16-bit) per call. Output starts after the
 * tracker's look-ahead: the first frame comes out on the 6th call. At the end, call
 * sotto_enc_flush until it returns 0 to get the remaining frames.
 *
 * Decoder: one call per received frame, with good = 0 when the frame failed its CRC (the
 * decoder then conceals it). Each call returns 160 samples, 20 ms behind: the first call
 * returns silence. sotto_dec_flush returns the last 20 ms.
 */
#ifndef SOTTO_H
#define SOTTO_H

#ifdef __cplusplus
extern "C" {
#endif

#define SOTTO_SAMPLES_PER_FRAME 160
#define SOTTO_BITS_PER_FRAME 48
#define SOTTO_BYTES_PER_FRAME 6

struct sotto_enc;
struct sotto_dec;

struct sotto_enc *sotto_enc_create(void);
void sotto_enc_destroy(struct sotto_enc *e);
/* Returns the number of frames written to out (0 or 1). */
int sotto_encode(struct sotto_enc *e, const short speech[SOTTO_SAMPLES_PER_FRAME],
                 unsigned char out[SOTTO_BYTES_PER_FRAME]);
/* Feeds a last 10 ms (80 samples) before the flush, for inputs that end mid-frame. */
void sotto_encode_half(struct sotto_enc *e, const short speech[SOTTO_SAMPLES_PER_FRAME / 2]);
/* Ends the stream. Returns 1 and writes a frame while frames remain, then 0. */
int sotto_enc_flush(struct sotto_enc *e, unsigned char out[SOTTO_BYTES_PER_FRAME]);

struct sotto_dec *sotto_dec_create(void);
void sotto_dec_destroy(struct sotto_dec *d);
void sotto_decode(struct sotto_dec *d, const unsigned char in[SOTTO_BYTES_PER_FRAME], int good,
                  short speech[SOTTO_SAMPLES_PER_FRAME]);
void sotto_dec_flush(struct sotto_dec *d, short speech[SOTTO_SAMPLES_PER_FRAME]);

#ifdef __cplusplus
}
#endif
#endif
