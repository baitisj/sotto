# The envelope quantizer: where its loss is, and a peak-weighted pick

*2026-11-19.* The FARGAN study ([fargan-study.md](fargan-study.md)) found that swapping in the
original 0-4 kHz envelope was worth +0.36 WB PESQ to FARGAN, more than the hiss bands or pitch. This
study asked how much of that sotto's own decoder can win back within the 34 shape bits, and how.

**Result.** The v3.8 encoder now picks the shape index by a peak-weighted error. The codebook, the
48-bit frame and the decoder are unchanged, so every existing decoder plays the new streams. Over
31 held-out 8 kHz voices narrowband PESQ goes from 3.095 to 3.139 (+0.044; 26 of 31 voices
better), and over the 10 voices of the v3.8 page wideband PESQ goes from 1.775 to 1.790 (+0.015).
The fixed-point encoder runs about 0.8% more instructions.

## How much is there to win

Most of the FARGAN figure is not reachable by a better quantizer in sotto. FARGAN's ablation
swapped in its own features: 13 bands every 10 ms, no 20 ms interpolation, at full precision.
sotto's envelope is 20 points from 200 to 3700 Hz, coded once per 20 ms, with the 10 ms frame in
between interpolated. With sotto's own decoder (`tools/env_vq_lab.py`):

| Shape the decoder gets | NB PESQ, 31 voices | WB PESQ, 10 voices (v3.8) |
|---|---:|---:|
| v3.8 encoder before this change | 3.095 | 1.775 |
| v3.8 encoder now (weighted pick) | **3.139** | **1.790** |
| Unquantized shape every 20 ms (a perfect quantizer) | 3.228 | 1.830 |

A perfect 34-bit quantizer would add +0.13 NB and +0.06 WB. The weighted pick takes a third of the
NB gap and a quarter of the WB gap. A further part sits in the 20 ms frame rate: on the 16 clean
voices, the true shape every 10 ms scores 3.107, against 3.040 for the true shape every 20 ms and
2.937 for v3.8. No quantizer can win that back without a 10 ms shape, which the frame has no bits
for.

## What changed

The M-best search keeps the 8 best paths through the 9+9+8+8 stages by plain squared error in dB,
as before. The final pick among those 8 used the same plain error. It now weighs the error at each
of the 20 rate-K points by

    w = 10^(-0.5 * min(x, 40) / 20),  x = dB below the frame's highest point

so a formant peak counts about 10 times more than a point 40 dB down in a valley. Plain dB error
spends the bits evenly across peaks and valleys. Ears, and PESQ, hear the peaks much more.

Code: `vocoder_lab.shape_weights`, `ShapeMSVQ.wpick`, `hiss_band.SottoV38.WPICK`; in C,
`SOTTO_WPICK` in `c/sotto.c` and `c/fixed/sotto_fx_enc.c` (on for VARIANT=v3.8, the default;
`-DSOTTO_WPICK=0` or `SottoV38.WPICK = None` gives the encoder before). The v3.7 build and the
sotto 1200 / 600 / 400 encoders are unchanged.

- **Float C:** 100% of frames bit-identical with the Python model (`tools/check_c_port38.py`, 3
  voices).
- **Fixed point:** 95.3% of frames identical to float, PESQ 3.041 against 3.043
  (`tools/check_fx.py --enc --v38`, the same 3 voices), the same agreement as before. About 3,400
  extra multiply-adds per 20 ms frame (an inverse DCT and weighted sum for each of the 8
  survivors), +0.8% instructions on x86 under Valgrind. On the C5517 that should be well under
  1.5 MHz on top of the 16 kHz encoder's 137 MHz mean and 157 MHz worst. Not measured in the TI
  simulator, which isn't installed in this container.
- The new encoder changes the shape index in about half of all frames, and 7% of frames in other
  fields too, because the v3.8 rules look at the encoder's own decoded output.

## Results

`python tools/env_vq_lab.py --json docs/results/envelope_vq.json` (about 4 minutes on 4 cores).
"Better" counts voices that improved against the first row. "Shape error" is the plain mean
squared error in dB² of the coded 20 ms shapes; it goes up, as expected, because the pick no
longer minimises it.

| Encoder | NB PESQ (31) | better | ESTOI | WB PESQ (10) | better | shape error |
|---|---:|---:|---:|---:|---:|---:|
| v3.8 before (plain pick) | 3.095 | | 0.807 | 1.775 | | 2.42 |
| **v3.8 now (weighted pick)** | **3.139** | 26 | 0.815 | **1.790** | 7 | 2.58 |
| weighted search from stage 3, weighted pick | 3.159 | 31 | 0.817 | 1.804 | 7 | 2.83 |
| weighted search in every stage | 3.155 | 29 | 0.816 | 1.792 | 6 | 2.94 |
| codebook retrained on 1,500 SC speakers, plain pick | 3.120 | 23 | 0.808 | 1.769 | 3 | 2.39 |
| the same, weighted pick | 3.141 | 26 | 0.814 | 1.791 | 6 | 2.56 |
| codebook trained for the weighted error, weighted pick | 3.148 | 27 | 0.815 | 1.799 | 8 | 2.58 |
| unquantized shape (ceiling) | 3.228 | 30 | 0.837 | 1.830 | 8 | 0 |

Test sets: the 16 clean held-out voices (8 LibriSpeech, 8 EARS), the 12 Speech Commands counting
clips and the 3 voices of the listening page, at 8 kHz, scored on v3.7's 8 kHz core (the same
envelope code as v3.8's 0-4 kHz). WB: the 10 LibriSpeech voices of the v3.8 page, full v3.8 at 16
kHz with its candidate settings. Retraining the shape quantizer alone moves single-voice PESQ by
about ±0.1, so rows within ±0.02 of each other are a tie.

## Tried and not adopted

- **Weighted search in the later stages.** Weighting stages 3 and 4 as well adds about +0.02 NB
  and +0.015 WB over the weighted pick: the next step if it holds up by ear. In fixed point it
  needs the two 256-entry stages in the rate-K domain (10 KB as int8) for the per-frame
  sum of w y², while the cross term can reuse `cb_dots` unchanged on the weighted residual turned
  back into DCT coefficients. Estimated +1-2 MHz on the C5517.
- **New codebooks.** Trained on 1,500 Speech Commands speakers (`tools/env_corpus.py`,
  `tools/train_shape_vqw.py`, CPU only, about 10 minutes each), with plain or weighted error.
  Neither beats the shipped codebook once the weighted pick is used, so the decoder's tables
  stay as they are. LibriSpeech could not be fetched in this session, so the shipped codebook
  (Speech Commands + LibriSpeech) had more varied training data.
- **Tuning the weight.** Exponents 0.4-0.7 and floors 30-50 dB all land within ±0.01 of each
  other on 31 voices; 0.5 and 40 dB were kept.
- **A free level offset** in the weighted error (the decoder sets the level from the energy field
  anyway): no gain.
- **Interpolation-aware search.** A Viterbi pass over each frame's 8 survivors that also scores
  the interpolated 10 ms frame in between: +0.008 NB over the weighted pick, for 20 ms more
  encoder delay. Not worth it.
- **Predictive (interframe) shape coding** was not retried. It was +0.05 clean but -0.2 over
  fading in the v1 work ([encoder-v1.md](encoder-v1.md)), and the ceiling above leaves only +0.09
  NB for any quantizer. Lattice and split VQ were not tried either: they would have to beat the
  4-stage M-best MSVQ inside that same +0.09.

## Reproduce

1. `make && make fixed`; Python 3 with numpy, scipy, scikit-learn, soundfile, pesq, pystoi.
2. `python tools/env_vq_lab.py [--codebook NAME=PATH ...] [--json OUT]`. It needs
   `/mnt/project-files/vocoder/samples-clean`, `samples-sc` and `samples15` (8 kHz test clips;
   `SAMPLES_CLEAN` points elsewhere) and `docs/samples/v38/*__original16.flac`.
3. Codebooks: `python tools/env_corpus.py sc SC_DIR sc.npz --speakers 1500 --exclude
   samples-sc/clips.json`, then `python tools/train_shape_vqw.py sc.npz --out cb.npz
   [--unweighted]`.
4. C against Python: `python tools/check_c_port38.py CLIP16K.wav ...`; fixed against float:
   `python tools/check_fx.py --enc --v38 CLIP16K.wav ...`.
