# sotto encoder v0: first oracle results

*Written 2026-10-31. Code: `sim/oracle_ladder.py`, `sim/vocoder_lab.py`, `sim/encoder_race.py`. Results: `docs/results/oracle_ladder_15s.json` and `docs/results/encoder_race.json`. Samples: `docs/samples/encoder/`.*

## Where Codec 2 2400 loses quality

`c2sim` was run on the three 15 s clips with one simplification added at each rung:

| Rung | Female | Male (LibriSpeech) | Male (ve9qrp) |
|---|---:|---:|---:|
| Sinusoidal model, true phases | 3.08 | 3.82 | 4.00 |
| + synthetic phase (voicing) | 2.78 | 3.52 | 3.27 |
| + postfilter | 2.77 | 3.54 | 3.48 |
| **+ LPC-10 envelope** | 2.61 | **2.98** | **2.94** |
| + scalar LSP quantization | 2.50 | 2.87 | 2.80 |
| + 2400 pitch/energy quantization, 20 ms | 2.33 | 2.90 | 2.63 |
| c2enc/c2dec 2400 | 2.16 | 2.91 | 2.85 |

- **For the men, the 10th-order LPC envelope is the largest single loss, about 0.55 PESQ.** Synthetic phase costs about 0.3 to 0.7.
- **The female clip starts low:** 3.08 even with true phases. That points at the analysis itself (pitch tracking, or too few harmonics to sample her envelope) more than at quantization.
- **Higher LPC orders barely help** (16: +0.1–0.2; 20: about the same). A mel-spaced "rate-K" envelope (20 amplitudes from 200 to 3700 Hz, as in Codec 2's newamp1) recovers most of the loss when unquantized: 2.67 / 3.43 / 3.31 against 2.77 / 3.54 / 3.48 with no envelope modelling at all.

## sotto v0

v0 is a 48-bit, 20 ms frame with no memory between frames:

| Field | Bits | Notes |
|---|---:|---|
| Voicing | 2 | one decision per 10 ms, from Codec 2's estimator |
| Pitch (Wo) | 7 | log-uniform, Codec 2's range |
| Frame energy | 5 | sum of harmonic powers, 10–80 dB; the decoded level matches the input |
| Envelope shape | 34 | DCT of the mean-removed 20-point mel envelope. Uniform scalar quantizers, with step sizes and a greedy bit allocation (5,4,3,3,2,…) trained on Codec 2's test recordings. The ve9qrp test window is excluded from training, and the LibriSpeech voices are never used. |

The decoder rebuilds harmonic amplitudes from the envelope and applies a newamp1-style formant postfilter (gain 1.5). It interpolates the 10 ms subframe and then uses Codec 2's synthesis (`c2sim --modelin --phase0 --postfilter`).

Inter-frame prediction of the shape (α = 0.5) gave a further +0.1 to 0.3 on two clips. It was left out of v0 because channel errors would carry into the next frame.

## Encoder against encoder

Both codecs send 48 bits every 20 ms through the identical chain: sotto VW payload, C4FM softmodem, the same fading seeds, and the same receiver with CRC concealment. PESQ is averaged over 3 seeds:

| Condition | Codec | Female | Male (LibriSpeech) | Male (ve9qrp) |
|---|---|---:|---:|---:|
| No radio channel | Codec 2 2400 | 2.16 | 2.91 | 2.85 |
| | **sotto v0** | **2.50** | **3.14** | **2.88** |
| 446 MHz 60 km/h, 52 dB-Hz | Codec 2 2400 | 1.69 | 2.29 | 2.49 |
| | **sotto v0** | **2.11** | **2.68** | **2.69** |
| 446 MHz 60 km/h, 56 dB-Hz | Codec 2 2400 | 2.16 | 2.72 | 2.78 |
| | **sotto v0** | **2.45** | **3.05** | **2.85** |
| 146 MHz 30 km/h, 56 dB-Hz | Codec 2 2400 | 1.82 | 2.06 | 1.91 |
| | **sotto v0** | **2.19** | **2.61** | **2.31** |

**sotto v0 is ahead in every condition and voice:** +0.03 to +0.34 with no channel, and +0.2 to +0.55 over fading channels. The fading gains may partly come from v0 being memoryless and its frames concealing more gracefully. The female voice gains the most with no channel (+0.34). She is still well below the men, which leaves pitch and voicing as the next targets.

## Caveats

- PESQ only, on three clips, and no listening panel yet. The formant postfilter may flatter PESQ. The level difference between the two codecs is under 1 dB.
- One training speaker (ve9qrp) is also a test speaker, though a different stretch of the recording. The LibriSpeech voices are fully held out.
- v0 is a Python and `c2sim` prototype, not yet a C encoder and decoder. Its analysis (pitch, voicing) and synthesis are still Codec 2's.

## Next

1. Pitch tracking and voicing for higher voices: check Codec 2's estimator on the female clip, and try mixed or band voicing (MBE/MELP-style).
2. Better shape quantization: trained VQ or predictive coding with error-resilient resets, which needs more training speech.
3. Port v0 to C inside `codec/codec2/` as a new mode, so it runs in real time and on the DSP.
