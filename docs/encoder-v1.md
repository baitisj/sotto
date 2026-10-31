# sotto encoder v1: pitch, voicing and quantizer experiments

*Written 2026-10-31. Follows [encoder-v0.md](encoder-v0.md). Code: `sim/sinusoid.py`, `sim/vocoder_lab.py` (`analyse(x, "tracked")`, `SottoV1`), `sim/encoder_race.py --codecs`. Results: `docs/results/encoder_race.json`. Tests: `tests/test_vocoder.py`.*

v0 left the female voice well behind the men, and the oracle ladder pointed at analysis (pitch, voicing) more than quantization. This round looked at pitch, then voicing, then the shape quantizer. The C port is still deferred.

## A Python analysis that matches c2sim

`sim/sinusoid.py` reproduces Codec 2's analysis (`sine.c`): the same 320-sample buffer, 279-point window, 512-point FFT, harmonic amplitudes and MBE voicing decision. Given Codec 2's pitch, the amplitudes match `c2sim --modelout` exactly, and the voicing matches on more than 99% of frames (the rest are float rounding at the 6 dB threshold). That lets us change pitch and voicing and still synthesise with `c2sim --modelin`.

The fork's `phase.c` gained one backward-compatible hook for the voicing experiments: a `voiced` value of k ≥ 2 means harmonics below k are voiced and the rest get random phase. 0 and 1 behave as before.

## Pitch: Codec 2 makes octave errors on the female voice

Against librosa's pYIN as a reference, Codec 2's pitch is off by more than 20% on 32% of the female's voiced frames, against 14% and 6% for the two men. The errors go both ways: about half are doubled, half halved. pYIN isn't ground truth either, since it clamps some of her frames to its 60 Hz floor.

Swapping pitch tracks with the vocoder's quantizers bypassed (Codec 2 synthesis with phase0 and its postfilter, so this measures analysis only):

| Pitch track | Female | Male (LibriSpeech) | Male (ve9qrp) |
|---|---:|---:|---:|
| Codec 2 | 2.77 | 3.54 | 3.48 |
| pYIN (offline, non-causal) | 3.07 | 3.19 | 3.57 |
| **sotto tracker** | **3.10** | **3.60** | **3.56** |

The **sotto tracker** (`sinusoid.track_pitch`) starts from Codec 2's estimate and, within each voiced stretch, considers that value, double it and half it, each refined with Codec 2's harmonic-sum search. A Viterbi search picks the path that minimises:

- the MBE fit error up to 2.5 kHz,
- a small bias toward the higher pitch, because a subharmonic fits about as well as the true pitch,
- a penalty on jumps between frames.

Candidates other than Codec 2's own must stay above 70 Hz, which stops it halving low male voices. It needs lookahead to the end of the voiced stretch. A real-time version will need a bounded window, probably 40 to 60 ms.

## Voicing: band voicing showed no PESQ gain

Band voicing (harmonics above a cutoff given random phase, from per-harmonic fit SNR) was tested at thresholds of 2, 4 and 6 dB. Each was tried with the cutoff free and with it quantized to 500/1000/2000/3000 Hz/full. Every variant scored within ±0.1 of plain binary voicing, and some were lower. Codec 2's postfilter already randomises weak harmonics, which covers part of the same ground. PESQ isn't a good judge of buzziness, so this is parked until we have listeners rather than dropped.

## Where the 48-bit codec loses quality

With the tracker in place, adding one step of v0 at a time (PESQ, female / male LibriSpeech / male ve9qrp):

| Step | Female | Male L | Male V |
|---|---:|---:|---:|
| Sinusoidal model, phase0 + postfilter | 3.10 | 3.60 | 3.56 |
| Rate-K envelope (20 mel points) | 2.90 | 3.46 | 3.17 |
| Envelope sent every 20 ms, interpolated | 2.76 | 3.35 | 2.96 |
| Pitch sent every 20 ms | 2.65 | 3.25 | 2.96 |
| 7-bit pitch, 34-bit shape | 2.45 | 3.00 | 2.55 |
| + formant postfilter (= v1) | 2.62 | 3.24 | 2.69 |

Things tried here that didn't earn their bits:

- **2-bit interpolation index for the in-between 10 ms frame** (oracle choice of weights): +0.02 to +0.07. Not worth 2 shape bits.
- **More envelope points** (K = 24 to 32, unquantized): +0.05 for two voices, noisy for ve9qrp. Possible later, since the extra high-order DCT coefficients get no bits anyway.
- **Predictive shape quantizer**, with per-coefficient first-order prediction (gains 0.6 to 0.8, fitted on the training set) and the decoder holding its state on CRC-failed frames. It scored +0.0 to +0.1 with no channel, but −0.1 to −0.26 at 446 MHz / 52 dB-Hz and at 146 MHz, because a lost frame still leaves the predictor out of step for several frames. v1 stays memoryless.

## Encoder against encoder

Everything goes through the same chain as before: sotto VW payload, C4FM softmodem, the same fading seeds, and the same receiver with CRC concealment. Mean of 3 seeds:

| Condition | Codec | Female | Male (LibriSpeech) | Male (ve9qrp) |
|---|---|---:|---:|---:|
| No radio channel | Codec 2 2400 | 2.16 | 2.91 | **2.85** |
| | sotto v0 | 2.50 | 3.14 | **2.88** |
| | **sotto v1** | **2.68** | **3.28** | 2.83 |
| 446 MHz 60 km/h, 52 dB-Hz | Codec 2 2400 | 1.69 | 2.29 | 2.49 |
| | sotto v0 | 2.11 | 2.68 | **2.69** |
| | **sotto v1** | **2.27** | **2.77** | 2.62 |
| 446 MHz 60 km/h, 56 dB-Hz | Codec 2 2400 | 2.16 | 2.72 | 2.78 |
| | sotto v0 | 2.45 | 3.05 | **2.85** |
| | **sotto v1** | **2.66** | **3.12** | 2.79 |
| 146 MHz 30 km/h, 56 dB-Hz | Codec 2 2400 | 1.82 | 2.06 | 1.91 |
| | sotto v0 | 2.19 | 2.61 | **2.31** |
| | **sotto v1** | **2.28** | **2.66** | 2.25 |

Compared with v0:

- **The female voice gains +0.1 to +0.2** everywhere. Against Codec 2 she is now +0.5 to +0.6 better.
- **The LibriSpeech male gains** +0.05 to +0.14.
- **ve9qrp loses** 0.05 to 0.07, which is within PESQ noise for these clips (retraining the shape quantizer alone moves ve9qrp by ±0.1). It is still well ahead of Codec 2 over the radio channels, and level with it with no channel.

The listening page now pairs Codec 2 with v1.

## What limits the next step: speech data

The shape quantizer is trained on about 2 minutes of speech, nearly all from one male (ve9qrp), and scored on three clips. That is enough to compare structures, but not to train a vector quantizer, which is the obvious next gain (the quantizer step above costs 0.15 to 0.4). Nor is it enough to tune the tracker without fitting the noise. The sandbox can't reach LibriSpeech, VCTK or CMU ARCTIC, only GitHub.

## Next

1. More training and test speech, ideally 30+ minutes from at least 10 speakers, half of them female. With that: a trained (split or multistage) VQ for the shape, and re-tuning the tracker on a held-out set.
2. A bounded-lookahead version of the tracker, so it can run in real time.
3. Listening checks for band voicing and the postfilter, which PESQ can't judge.
4. The C port of v1 (deferred).
