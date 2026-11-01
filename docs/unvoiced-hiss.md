# Unvoiced consonants: level, spare bits and 4-8 kHz hiss

Status: prototype and listening round 11, not in the encoder. 2026-11-01.
Measured against v3.6. v3.7, merged while this ran, changes only the pitch tracker (same
decoder and bitstream), so the findings carry over; a v3.8 would build on v3.7. Round 11 (version 2 of the page)
and tools/hiss_proto/ are on v3.7: Jeff spotted v3.6's 490 Hz pitch jump on p020 in pair 1.

Jeff's question: would s, sh and f sound more natural if unvoiced consonants got more
bandwidth, starting from a default spectral template and refined during pauses or low-rate
intervals, with some simple high-frequency hiss shaping?

## What is wrong with s/sh/f in v3.6

Measured over the 16 held-out voices, on frames where 2.5-4 kHz is louder than 0-1 kHz
(`tools/hiss_proto/diag3.py`):

| Step | 0-1 kHz | 1-2 kHz | 2-2.5 | 2.5-3 | 3-3.5 | 3.5-4 kHz |
|---|---|---|---|---|---|---|
| Unquantized model, rate-K envelope | -3.2 | -3.2 | -3.0 | -3.1 | -3.1 | -3.7 dB |
| + 20 ms decimation | -3.2 | -3.5 | -3.1 | -3.3 | -3.5 | -4.0 |
| + 34-bit VQ | -3.3 | -3.4 | -3.4 | -3.4 | -3.4 | -4.0 |
| + postfilter (= v3.6) | -8.5 | -4.1 | -3.4 | -3.1 | -3.8 | -3.1 |

So inside 0-4 kHz the fricatives have about the right shape but are about 3 dB too quiet.
Quantization adds almost nothing. The loss comes from two places:

- Random-phase harmonics overlap-added with the 10 ms triangular window lose 1.76 dB
  (the mean of w² + (1-w)² is 2/3). Codec 2 has the same loss.
- The rate-K envelope samples a noisy harmonic spectrum and interpolates it in dB, which
  averages logs rather than powers: about 1.3 dB more.

Above 4 kHz there is nothing, because the codec runs at 8 kHz. In studio recordings
(EARS) most of the energy of "s" is at 4-8 kHz.

## The spare bits

- **Pauses are not silent.** Energy code 0 (digital silence) is about 0% of frames in
  real read speech, because pauses carry room noise. So "pauses" means all-unvoiced frames.
- **All-unvoiced frames (voicing code UU) are 24% of frames**, and their 7 pitch bits are
  almost unused. The pitch only sets the spacing of the noise harmonics. With a fixed
  50 Hz spacing in unvoiced halves, PESQ is 2.916 against v3.6's 2.914 over 19 voices
  (`p_eval.py`). (A fixed 100 Hz spacing costs 0.024, because 100 Hz harmonics with
  random phase repeat every 10 ms and sound rough.) That frees 7 bits × 24% × 50 frames/s
  ≈ 84 bit/s.
- Mixed (MM) and edge frames still need their pitch, so voiced fricatives like z and v get
  no spare bits.

## Ways to spend them, and what each is worth

| Option | Bits | Result |
|---|---|---|
| Level fix: unvoiced halves +3 dB, 50 Hz noise spacing | 0 | PESQ 2.900 vs 2.914 (within PESQ noise; +1.5 dB is neutral). Needs ears. |
| Better s/sh envelope inside 0-4 kHz (7-bit extra VQ stage in UU frames) | 7 in UU | Ceiling with a perfect envelope in UU frames: +0.03 PESQ. Not worth it. |
| 4-8 kHz hiss, decoder guess from the 0-4 kHz envelope | 0 | Band levels off by 11-14 dB rms on unvoiced frames: about as bad as a constant. |
| 4-8 kHz hiss, 7-bit index (4 band levels, residual of the guess) in UU frames | 7 in UU | Error about 6 dB rms (5.5 LibriSpeech, 6.8 EARS). |
| Per-speaker template, refined slowly in pauses | ~84 bit/s | Ceiling (the speaker's exact mean, on the test clip itself): 14.4 → 12.0 dB on EARS unvoiced frames. Much smaller gain than the per-frame index. |
| Carry the last UU index into mixed frames (z, v) | 0 | 14.8 → 13.9 dB: does little. Voiced fricatives stay narrowband. |

Errors are rms dB over four bands (4-5, 5-6, 6-7, 7-8 kHz) on 12 held-out voices (8
LibriSpeech, 4 EARS). Trained on 32 other LibriSpeech dev-clean speakers (CC BY 4.0); no
EARS audio is used in training.

So Jeff's "default plus adaptive refinement" works best as a default guess plus a
per-frame correction in the frames that are the fricatives, not as a slow template. The
template mostly fixes the microphone and room, which a per-frame index already covers.

Wideband PESQ does not help choose: with the true 4-8 kHz levels, adding noise only to
unvoiced frames lowers WB-PESQ (1.70 → 1.60), while adding it to all frames raises it
(1.86). WB-PESQ punishes noise added where the reference has structure, so this is a
listening question (round 11).

## Prototype (tools/hiss_proto/)

- `proto.py`: decoder with 50 Hz unvoiced spacing and unvoiced gain (uses two new hooks in
  `SottoV0.decode`, `_frame_hook` and `_model_hook`, which do nothing by default).
- `hiss.py`: the hiss7 codec. The encoder takes 16 kHz input, codes the 8 kHz part as v3.6,
  runs its own decoder to get the guess, and writes the 7-bit residual index into the pitch
  field of UU frames. The decoder upsamples to 16 kHz and adds random-phase noise above
  3.9 kHz (sqrt-Hann, 20 ms frames, 10 ms hop) in UU frames and in the unvoiced half of a
  neighbouring edge frame. Lost frames reuse the concealed bits and the concealment fade.
  `hiss_model.npz` is the trained guess (3 × 8 × 4 coefficients) and codebook (128 × 4).
- `render_ab11.py`: listening round 11. Paths in these scripts point at the sandbox
  (`/tmp/claude-0/...`), since the 16 kHz clips are not in the repository.

## Cost on the C5517

- Bits: none added; the frame stays 48 bits. A v3.6 decoder reading a hiss7 stream would
  take the index as a pitch for the noise spacing (harmless but rougher), so this is a new
  stream version.
- Decoder: 2× upsampling (half-band FIR, about 0.2 M MAC/s), one 320-point inverse FFT per
  10 ms for the hiss (the C5517 has an FFT accelerator), and up to 80 instead of 40 noise
  harmonics in unvoiced halves (about 0.6 M MAC/s worst case). About 1-1.5 MHz on top of
  the 4-8 MHz estimate.
- Encoder: 16 kHz input and a 2× decimator, one 320-point FFT per 10 ms for the band
  levels, the guess (32 MACs) and a 128 × 4 search per UU frame. Under 1 MHz.
- Memory: about 1 KB of tables. Everything is dB arithmetic on 4 bands, which fits the
  existing Q8 dB style in `c/fixed/`.
- **Open question: the radio's audio path.** The hiss only matters if the FTM-300D's mic
  path and speaker pass 4-8 kHz. The AIC3204 can run at 16 kHz, but the mic preamp
  filtering and the speaker response are unknown. AMBE runs at 8 kHz, so the stock
  firmware may never have needed more.

## Listening round 11

https://claude.ai/artifact/V8Y9EfZ32XLFFQ8kvXSAqh, key
`/mnt/project-files/vocoder/listening/ab-11-key.json`. Pairs: v3.6 vs level (2), v3.6 vs
hiss7 (5), level vs hiss7 (2), v3.6 vs hiss0 (1), null (1). Original in every pair; 5 of
the 11 pairs over fading 70 cm and 2 m.

Round 11 result (Jeff): the hiss version (hiss7) won every pair answered: 4 of 4 against
v3.7 (two clean, two fading) and 2 of 2 against the level fix alone. The decoder guess beat
v3.7 1 of 1. Level fix vs v3.7: 2 ties, so the 3 dB alone isn't audible. Notes: t (pair 1,
p020) and p (pair 7, p095) need more high-frequency hiss; Jeff asked to keep watching p047
(pair 8), where all consonants sound thin.

## t, p and k bursts (round 12)

Stop bursts usually run straight into the vowel, so their frame is coded mixed or edge and
gets no hiss index. Over the 12 test voices, the first 30 ms after a burst onset (4-8 kHz
jumps by more than 12 dB in 10 ms and is within 15 dB of 0-4 kHz) came out 7.1 dB short
(`bursts2.py`):

| Variant | Burst shortfall, 4-8 kHz | Band error, all live frames | Narrowband PESQ |
|---|---|---|---|
| hiss7 | -7.1 dB | 19.1 dB | 2.810 |
| + decoder guess in mixed frames (-3 dB), "m" | -5.3 | 17.4 | 2.810 |
| + burst frames sent as UU, "b" | -2.8 | 18.9 | 2.801 |
| both, "bm" | -2.4 | 17.3 | 2.801 |

The burst rule turns about 6 frames per 12 s into UU, so they lose 20 ms of low-frequency
voicing at the vowel onset (that stretch is mostly aspiration anyway) and gain an index.

p047 (`p047.py`): its 135 mixed frames outnumber its 86 unvoiced ones. Unvoiced frames are
now right (4-8 kHz within 0.2 dB). Mixed frames are 3 dB low at 2-3.9 kHz and 19 dB short
at 4-8 kHz with hiss7, 10 dB short with "bm". The rest of the gap is the conservative -3 dB
on the guess, and the mixed frames' noise harmonics losing the same 1.76 dB as unvoiced
ones.

Round 12: https://claude.ai/artifact/6Jafb6jidSvJncesyjgS7J, key `ab-12-key.json`:
hiss7 vs bm (5, including p047 clean as pair 10 and fading as pair 8), hiss7 vs b (2), b vs
bm (2), null pair 1.
