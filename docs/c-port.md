# sotto on the C5517: C port and budget

*2026-10-31. The float C port is in `c/`, and `c/README.md` explains how to build and run it.
This page covers what the radio's DSP needs that the float port doesn't have yet.*

## What exists

- **`c/`** is a float C port of v3.5. It has a streaming encoder whose pitch tracker decides
  each frame 80 ms late (fixed-lag Viterbi). It also has a decoder with v3.5's concealment.
  Both link Codec 2 for the sinusoidal analysis, phase synthesis, postfilter and overlap-add.
- **Check against Python.** On 19 voices, 11,170 of 11,173 frames are bit-exact with
  `SottoV35` running the same 80 ms tracker. Given the same bits, the two decoders agree to
  about 100 dB SNR (`docs/results/c_port_check.json`, from `tools/check_c_port.py`).
  - The 3 frames that differ are octave near-ties in the tracker.
  - The C side uses Codec 2's float FFT and the Python side uses double precision.
- **Delay.**

  | Stage | Delay |
  |---|---|
  | Encoder look-ahead | 90 ms (80 ms tracker + 10 ms for the next frame's pitch candidate) |
  | Frame | 20 ms |
  | Decoder interpolation | 20 ms |

  On the air, you then add the YSF frame (100 ms), plus another 100 ms if you use depth-2
  interleaving.

## Where the time goes

Measured on one x86 core with gprof, 60 s of speech:

| Part | Share of encoder time |
|---|---:|
| Shape VQ, M-best search (12+11+11 bits, M = 8) | 90% |
| Pitch tracker candidates (harmonic-sum refinement, fit error, odd/even check) | 9% |
| Codec 2 analysis (nlp, FFT, refinement, voicing) | under 3% |

The encoder runs at 3% of real time and the decoder at 0.1%.

The VQ search costs about 700,000 multiply-adds per 20 ms frame:
- stage 1 compares the target with 4,096 vectors;
- stages 2 and 3 each compare 8 surviving paths with 2,048 vectors;
- each vector has 19 dimensions.

That is 35 million multiply-adds a second. The C5517 has two 17×17-bit MACs at up to
200 MHz, so in 16-bit fixed point the search would need about 20 to 30 MHz. That is too
much to spend on one block when the C4FM modem has to share the DSP.

## Memory, and a smaller codebook

The C5517 has 320 KB of on-chip RAM: 64 KB dual-access and 256 KB single-access. Yaesu's
modem and whatever replaces AMBE have to share it. The shipped codebook has 155,648 values.
It needs 608 KB as float, 304 KB as 16-bit and 152 KB as 8-bit, so it doesn't fit as it is.

Smaller layouts were trained on the same data (Speech Commands 600 + LibriSpeech 32 + Codec 2
recordings). They keep the 34 bits, so the frame doesn't change. Scores are v3.5 on 19
voices, clean channel, 80 ms tracker:

| Codebook (bits per stage) | Values | 8-bit size | VQ multiply-adds per frame | PESQ | ESTOI |
|---|---:|---:|---:|---:|---:|
| 12 + 11 + 11 (shipped) | 155,648 | 152 KB | 700,000 | 2.917 | 0.80 |
| 12 + 11 + 11, values rounded to 8 bits | 155,648 | 152 KB | 700,000 | 2.908 | 0.80 |
| 12 + 11 + 11, rounded to 6 bits | 155,648 | 114 KB | 700,000 | 2.898 | 0.80 |
| **9 + 9 + 8 + 8** | 29,184 | **29 KB** | **165,000** | **2.913** | 0.80 |
| 10 + 8 + 8 + 8 | 34,048 | 33 KB | 136,000 | 2.915 | 0.80 |
| 9 + 9 + 8 + 8, M = 16 | 29,184 | 29 KB | 321,000 | 2.896 | 0.80 |
| 9 + 9 + 8 + 8, M = 16, rounded to 8 bits | 29,184 | 29 KB | 321,000 | 2.904 | 0.80 |
| 8 + 8 + 6 + 6 + 6 | 13,376 | 13 KB | 73,000 | 2.881 | 0.80 |

Differences under about 0.02 are within the noise of 19 clips. The small layouts were also
trained with Codec 2's recordings, which include the ve9qrp voice. So read the table as
showing that **a codebook a fifth the size loses nothing measurable**, not that one layout
beats another.

- **Codebook for the DSP: 9 + 9 + 8 + 8 with M = 8, stored as 8-bit values.** It needs
  29 KB of RAM and 165,000 multiply-adds per frame, about 4 to 6 MHz on the C5517.
  - It is saved as `sim/data/shape_msvq_9988.npz`.
  - `make -C c CODEBOOK=sim/data/shape_msvq_9988.npz` builds the C port with it. The
    check gives bit-exact frames on 3 voices.
  - The float encoder runs 3 times faster with it.
- Switching codebooks changes the bitstream, so the radio and the PC tools must use the
  same one. The Python default (`SottoV35`) still uses the 12 + 11 + 11 book. The switch
  should be a named version, v3.6, after a listening check.
- Rounding to 8 bits costs about 0.01 PESQ. Rounding to 6 bits costs about 0.02.

## Fixed point: the plan

The C55x has no floating-point unit. Software float would be far too slow for the analysis
and synthesis, so the DSP build needs a fixed-point version of every block, not only
sotto's. In order:

1. **Codec 2's analysis and synthesis in fixed point.**
   - FFTs on the C5517's hardware FFT accelerator, with block floating point for the spectra.
   - nlp, harmonic-sum refinement, amplitudes and the MBE voicing fit.
   - Zero-phase synthesis (128-point FFT, log and exp tables).
   - Postfilter and overlap-add.

   Codec 2 has no official fixed-point version, so this is the largest piece. A fixed-point
   reference that compiles on x86 comes first, then the C5517 build. The x86 reference uses
   ETSI-style basic operations, so the same C runs on both.
2. **sotto's own blocks.**
   - The tracker's costs as base-2 logs in Q8.
   - The rate-K envelope in Q8 dB.
   - 8-bit codebooks with a 32-bit accumulator search.
   - Interpolation and set-energy with a table exp.
3. **Encoder memory.** The float encoder keeps 16 frames of 512-point spectra (70 KB) so the
   tracker can revisit them after its 80 ms delay. The DSP version should keep the last
   1,200 input samples (2.4 KB) instead, and redo the FFT for the frame being decided. The
   FFT accelerator makes that cheap.
4. **Check against the float port** with `tools/check_c_port.py` (PESQ within 0.05 and the
   same bits on most frames). Then measure cycles with TI's free C55x compiler and its
   simulator, or on a C5517 evaluation board.

None of this needs the radio. Running it on the radio still depends on the DSP update path
(workstream 3), which is open.
