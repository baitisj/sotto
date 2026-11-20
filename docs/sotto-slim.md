# sotto 1200 slim encoder: a transmitter for the UV-K6

*2026-11-19. `c/fixed/sotto_fx_slim.c` (API `c/fixed/sotto_slim.h`), bench driver
`c/fixed/slim_enc.c` (`make -C c fixed/sotto_slim_enc`), Cortex-M0 bench
`tools/cm0_slim_build.sh` and `c/fixed/cm0/run_slim.py`, tests `tests/test_slim.py`.*

The K6 plays sotto 1200 but could not make it: the fixed-point encoder needs seven times the
radio's processor and twice its whole RAM. This is a second encoder for the same bitstream. It
writes ordinary sotto 1200 superframes ([sotto-1200.md](sotto-1200.md)), the decoder is
untouched, and it trades a little quality for a very large cut in work.

## The budget

The K6's MCU is a 96 MHz Cortex-M0 with no 64-bit multiply, no divide and no count-leading-zeros
instruction. A module gets a 15,408-byte block of RAM for its code, tables and working memory,
and the shape codebook (30,720 bytes) sits in SPI flash at about 34 µs a vector read.

Measured on the Cortex-M0 cycle bench (`c/fixed/cm0/run.py`'s timing model, clang 18):

| | Full encoder (`sotto_fx_enc.c` + `sotto_fx_lr_enc.c`) | Slim encoder |
|---|---:|---:|
| Clock for real time, mean / worst superframe | 708 / 759 MHz (flash, `-O2`) | **27 / 29 MHz** (code in RAM, `-Oz`) |
| | | 21 / 22 MHz (RAM, `-O2`); 37 / 40 MHz (flash, `-Oz`) |
| State | 26,504 B | **3,148 B** |
| Stack | 7,544 B | **676 B** (`-Oz`) |
| Bench image, the 30,720 B codebook included | 109,233 B (`-O2`) | **41,404 B** (`-Oz`), 52,220 B (`-O2`) |
| of which code and tables without the codebook | | **10,684 B** (`-Oz`) |
| Codebook vectors read per superframe | every one, for up to 8 paths (in memory) | **about 150** (5 ms of SPI reads) |

Where the full encoder's 708 MHz goes: 360 in the 64-bit multiply helper (the M0 has none), 138
in the 8-path codebook search, 77 in the 10 ms analysis, the rest in harmonic fits, divisions
and FFTs. The slim encoder's 27 MHz: 11.5 pitch search, 6.9 envelope (FFT included), 3.1
codebook, 2.6 division helper, 1.6 moving its history.

On the radio that is about 28 % of the processor for the encoder and 13 % for the SPI reads.

## What it does differently

**Pitch and voicing in the time domain.** The full encoder fits harmonics to a 512-point
spectrum every 10 ms for ten pitch candidates. The slim one low-passes and decimates the input
to 4 kHz, takes a normalised cross-correlation over lags 8 to 80 (500 to 50 Hz) every 10 ms on
a 30 ms window, keeps up to four peaks, and runs a small Viterbi over them with 20 ms of
look-ahead. The same Viterbi makes the voicing call: one more state, "unvoiced", whose cost
rises with the best correlation and falls when the energy sits above 1 kHz. Three additions
came from watching it fail:

- a one-pole high-pass on the pitch path and a mild preference for shorter lags, against
  octave-low picks;
- the talker's usual pitch, learned from strongly voiced frames, as a weak prior;
- a hum test: when a window's first difference holds under 1/16 of its energy, nearly all of
  it is below 200 Hz and there is no voice to track. Without it, mains hum in a recording's
  pauses is coded as a steady 60 Hz voice.

**The envelope once per 20 ms.** One 256-point Hann window and a 16-bit 256-point FFT per
frame, the power summed in a band around each harmonic, interpolated to the 20 rate-K
frequencies, then the DCT. Unvoiced frames use bands 200 Hz wide. With the full encoder's pitch
and voicing this envelope loses nothing measurable against the full encoder's.

**A codebook search by cells.** `tools/gen_slim_ivf.py` groups each stage's vectors into 64
cells (32 for stage 3) by their first 8 values (`c/fixed/slim_cells.h`, 3.0 KB). The encoder
compares its target with the centroids, in RAM, and then reads only the vectors of the 3
nearest cells: about 30 vectors a search instead of 256 or 512. Comparing every vector instead
(`-DSLIM_FULL_SEARCH`) gains 0.01 PESQ.

**Two candidates instead of eight paths.** The full coder keeps 8 paths through stages 1-2 and
picks A's shape jointly with the B frames on both sides and the next A. The slim coder keeps
the 2 nearest stage-1 vectors, completes each, and takes the one with the least error over
this A frame and the B frame before it. That needs no extra look-ahead. One candidate instead
of two costs another 0.03 PESQ.

Everything is 16 x 16 -> 32-bit arithmetic. The state lives in the caller's memory
(`slim_enc_bytes()`), and the codebook is reached through `SLIM_CB_FETCH(stage, vector, buf)`,
which the K6 build points at its SPI read. Three more hooks let a platform keep the rest of the
read-only data out of RAM, with the same bits out: `SLIM_IVF_CEN(stage, c0, buf)` gives 16 cell
centroids at a time and `SLIM_IVF_CELL(stage, cell, v)` a cell's vector numbers (the 2.9 KB of
`slim_cells.h`), and `SLIM_DCT(j, i)` an entry of the 800-byte DCT table, which takes only 21
distinct magnitudes. The K6's FM receiver module (blowfang `c/k6/mod/fmsotto.c`) reads the
cells from a deck in its SPI module library and computes the DCT from 21 values.

## What it costs in quality

PESQ-NB and ESTOI through the fixed-point sotto 1200 decoder, original against decoded at the
codec's 160-sample delay. Set A: the 16 held-out voices of the vocoder comparison (EARS and
LibriSpeech, 12 s each), which the slim encoder's constants were tuned on. Set B: 19 voices it
never saw while tuning (Speech Commands talkers, LibriSpeech, Codec 2's samples).

| Encoder | Set A PESQ / ESTOI | Set B PESQ / ESTOI | 35-voice PESQ |
|---|---:|---:|---:|
| Full fixed-point encoder | 2.605 / 0.763 | 2.874 / 0.726 | 2.751 |
| Slim analysis, full coder | 2.573 / 0.762 | 2.854 / 0.724 | 2.726 |
| Full analysis, slim coder | 2.527 / 0.756 | 2.800 / 0.719 | 2.675 |
| **Slim encoder** | **2.530 / 0.755** | **2.803 / 0.714** | **2.678** |
| Slim, every vector compared | 2.532 / 0.756 | 2.818 / 0.720 | 2.687 |
| Slim, one candidate | 2.497 / 0.751 | 2.778 / 0.714 | 2.650 |
| Codec 2 1200 (for scale, set A) | 2.157 / 0.682 | | |

So the slim encoder gives up 0.07 PESQ and 0.01 ESTOI, and most of that is the coder, not the
analysis. Single voices spread more than the mean: on set A from 0.20 below the full encoder to
level with it, on set B from 0.35 below to 0.20 above, with 4 of the 19 more than 0.2 below.

Known weak spots, all in the pitch tracker:

- **A low, creaky voice with a strong first formant** can be coded at the formant's period
  (350-450 Hz) for 100-200 ms, where the full encoder holds 50-90 Hz (`hts1a`'s last word). A
  test that marks down lags with nothing at their double fixed those frames and cost 0.06 to 0.09 PESQ
  over the sets, so it is not in.
- **Voices above 350 Hz** are tracked at a half or a quarter of their pitch by both encoders;
  the slim one moves between sub-multiples more often.
- **Pitch below 50 Hz** is outside its lag range.

## Using it

```
make -C c fixed/sotto_slim_enc
c/fixed/sotto_slim_enc IN.raw OUT.bit            # 8 kHz 16-bit in, 6-byte superframes out
c/fixed/sotto_dec_fx -1200 OUT.bit OUT.raw
```

`-a full` or `-c full` puts the full encoder's analysis or coder in the slim one's place, for
tables like the one above. A build with `SLIMFLAGS=-DSLIM_TUNE` reads tuning knobs from the
environment (`SLIM_TUNE="14=4,15=3"`: 4 cells probed, 3 candidates).

In C, 10 ms at a time:

```c
slim_enc_t *e = malloc(slim_enc_bytes());
slim_enc_init(e);
while (read80(x)) if (slim_encode10(e, x, out)) send6(out);
while (slim_flush(e, out)) send6(out);
```

The cycle bench: `sh tools/cm0_slim_build.sh -Oz`, then
`python3 c/fixed/cm0/run_slim.py --profile --bits M0.bit IN.raw`. The M0 build's superframes
are the PC build's, bit for bit.

## On the K6: what is left

- **The radio has no microphone path into the MCU.** The mic goes straight to the FD6818's
  modulator. The only audio the MCU can read today is received FM, demodulated from the chip's
  GP0 IF stream. So the first on-radio use is to listen to an FM signal and encode it; a live
  microphone needs a probe of the chip's transmit-side GP0 codes first.
- **RAM.** Code and tables (10.7 KB) plus state (3.1 KB) leave about 1.6 KB of the 15,408-byte
  block for the audio front end and the message. A real-input FFT (512 B of state), the DCT
  from a 21-entry cosine table (0.7 KB) and the cell lists read from a library slot (1.3 KB)
  would give that back.
- **SPI time** is taken from the pager's measured 34 µs a read; a cell's vectors are scattered
  through the codebook, so each is its own read.
