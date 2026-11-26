# Harmonic phase watermark (prototype)

A few dozen bits per second hidden in FM voice itself, so they pass through a repeater the way
the speech does (a CTCSS tone or subaudible data is filtered off by the repeater's 300 Hz
high-pass and regenerated). The use in mind is a digital "tone squelch": a short ID frame
(callsign plus a one-byte code) that a receiver decodes after a few seconds of talking.

Try it in the browser: [docs/watermark.html](../docs/watermark.html)
(https://baitisj.github.io/sotto/watermark.html), which runs the C port below as WebAssembly.

## How it works

- sotto's pitch tracker (`sim/vocoder_lab.analyse(x, "tracked4")`) gives F0 every 10 ms.
- Each harmonic k is heterodyned by k·F0 and low-passed at 30 Hz: `z_k = (a_k/2) e^{j psi_k}`.
- For an odd harmonic k and its even neighbours, `D_k = arg(z_{k+1} z_{k-1} / z_k^2)` does not
  depend on the fundamental's phase, so it ignores where the receiver starts, a pure channel
  delay, and small pitch errors (they rotate z_k at a rate proportional to k, which the second
  difference cancels).
- The sender rotates every odd harmonic between 500 and 2600 Hz by the smallest angle (at most
  90°) that sets `D_k` to 0° (bit 0) or 180° (bit 1) for a 32 ms slot, blending between slots
  over 8 ms. Even harmonics stay as the reference. The band is split into four log-spaced
  sub-bands, each carrying its own bit, so a voiced slot carries 4 bits.
- Slots sit on a fixed time grid. Unvoiced slots carry nothing and the receiver treats them as
  erasures, so voicing disagreements never slip the bit stream.
- The sender marks against the pitch a receiver will see: the track of its own speech after a
  300-3000 Hz filter, and only where that agrees within 5% with the full-band track. Without
  this, the two ends tracking differently was the largest error source (6-10% bit errors
  through a noiseless repeater, down to about 3.5%).
- The receiver tracks the pitch of what it hears, finds the slot timing blindly (the offset
  where the soft values line up best as BPSK), removes the filters' phase bend per frequency
  bin (squaring estimate, unwrapped from mid-band), and sums soft bits per coded bit.
- Frame (`fec.py`): 32-bit base-40 callsign, 8-bit code, CRC-16, K=7 rate-1/2 convolutional
  code (124 coded bits), whitened, spread over the grid by a stride permutation and sent over
  and over. The receiver tries every codeword start, accepts a frame only with 80% of coded
  bits heard, a soft agreement of 0.9 or more, and the same frame decoding twice running.
  Whitening matters: natural speech leans `D_k` toward 0°, which otherwise decodes into frames
  near the all-zero codeword and gave false IDs on unmarked speech.

## Channel model (`fmchan.py`)

750 µs pre-emphasis, mic gain with speech peaks at the limiter (`drive_db` +6 for a loud
talker), hard deviation limiter, 3 kHz splatter filter, 100 Hz CTCSS, FM at 2.5 kHz deviation,
white noise at a carrier-to-noise ratio in 12.5 kHz, IF filter, discriminator, de-emphasis,
300-3000 Hz voice filter. A repeater is two hops: user to repeater at `cnr_in`, repeater audio
re-emphasised, limited and sent to the listener at `cnr_out`.

## Results (2026-11-26, LibriSpeech 251 male and 3536 female, 12 s each)

Raw: slot bits read where the sender marked (bits/s of talking, share wrong). ID: seconds of
talking until the frame decoded and confirmed.

| Channel | 251 raw | 251 ID | 3536 raw | 3536 ID |
|---|---|---|---|---|
| 300-3000 Hz filter only | 51 bit/s, 3.1% | 2.8 s | 46 bit/s, 8.3% | 3.6 s |
| Simplex FM, 25 dB | 49, 12.7% | 3.6 s | 42, 14.0% | 5.1 s |
| Repeater, 40 dB both hops | 46, 10.8% | 2.8 s | 41, 13.9% | 4.3 s |
| Repeater, 25 dB | 44, 12.8% | 3.6 s | 40, 17.9% | 8.2 s |
| Repeater, loud talker (+6 dB into limiter) | 47, 15.4% | 3.6 s | 41, 17.6% | 5.4 s |
| Repeater, 15 dB input | 37, 18.5% | 6.1 s | 35, 17.3% | 8.2 s |
| Repeater, 10 dB input | 29, 20.7% | 9.7 s | 29, 22.7% | 6.1 s |

Unmarked speech through the same 14 channel runs: no ID decoded, right or wrong. Narrowband
PESQ of marked against original: 4.07 (male), 3.82 (female); PESQ is mostly blind to phase, so
the ear decides. A narrow variant (900-2000 Hz, 2 sub-bands) scores 4.41 / 4.07 but needs 6 s
through a strong repeater and missed the ID on the female clip at 25 dB.

Strength sweep (rotation as a fraction of the full amount, 2 sub-bands): 0.6 leaves 16-20% bit
errors through a 25 dB repeater, 0.4 gives 24-27% even on a clean wire, because the speech's own
phase pattern leaks through. Full rotation stays.

## Over the air (2026-11-26)

`ota.py prep` writes the transmit WAVs and `ota.py read` decodes a capture. Bench jobs went
through the blowfang bench inbox on 441.850 MHz with an AG7EW ident.

- **wmota-1** (Pluto sends, the same Pluto listens in the background): only noise came back.
  A Pluto can't hear its own transmission, because transmit and receive share one baseband
  sample rate and `send` sets it to 2.4 MS/s under the running capture. Not a watermark
  result.
- **wmota-2** (IC-7100 sends, Pluto listens): the IC-7100 sent the plain marked speech at RF
  power 0 through its own FM transmit chain (data-mode USB audio, its pre-emphasis, limiter and
  filters), then the unmarked speech as a control. The Pluto received the flat discriminator
  audio, and `ota.py read --audio` de-emphasised it and band-limited it to 300-3000 Hz.
  The IC-7100 was used because a second transmitter was needed.

| Sent | 251 raw | 251 ID | 3536 raw | 3536 ID |
|---|---|---|---|---|
| Marked | 41 bit/s, 8.1% | 3.6 s, AG7EW | 42 bit/s, 11.0% | 4.1 s, AG7EW |
| Unmarked control | 47% wrong | none | 45% wrong | none |

## Run it

The pitch tracker imports `sim/audio_race.py`, which needs `pesq`, and runs `c2sim`, so build
the repository first (`make`) and use a Python with numpy, scipy, soundfile and pesq.

```sh
python watermark/run.py CLIP.flac --control --out OUTDIR   # all channels, JSON per channel
python watermark/listen.py OUTDIR CLIP.flac ...            # the listening set, each file checked
python watermark/selftest.py                               # synthetic vowel, numpy + scipy only
```

`watermark/page/index.html` is the listening page template (`__RESULTS__` is filled from
`run.py`'s result.json files).

## Next

- A handheld's own receiver (UV-380 FM tap) and a real repeater.
- A causal receiver: fixed-lag pitch tracking and causal heterodyne filters (about 50 ms delay).
- Fewer audible changes for the same bits: choose among several equivalent codewords the one
  closest to the speech's own phases (wet-paper or syndrome-trellis coding), and weight the
  rotation by masking.
- Receiver voicing: about a tenth of the slots the receiver reads were not marked; a better
  voicing match or a per-slot "marked?" test would cut those errors.

## C port and the browser page (`c/`)

`c/wm.c` is the sender, receiver, ID frame and FM channel in C, step for step as the Python
(`check_c.py` holds them to 1e-11 on the synthetic vowel with a known pitch track).
`c/wm_track.c` takes the pitch track from sotto's own C encoder (`c/sotto.c`); on the two test
clips it agrees with `tracked4` within 5% on 99.6% and 100% of the frames both call voiced, and
C-marked audio decodes with the Python receiver and the other way round. `c/wm_tables.h` (the
filters and the whitening sequence) is written by `c/gen_tables.py`.

The page's receiver works as the audio arrives: every 256 ms it re-reads everything heard so far
(timing, equaliser, polarity) and tries the decode; an ID counts when the same frame decodes twice
running. On the 8 kHz clips that gives the same ID times as `run.py` through a strong repeater
(2.8 s male, 4.4 s female).

Resampling matters: the page first used a short windowed-sinc to bring 16 kHz audio to 8 kHz, and
the male clip's ID through the strong repeater took 5.1 s instead of 2.8 s. It now resamples as
`scipy.signal.resample_poly` does (to 3e-8).

```sh
make -C watermark/c && python watermark/check_c.py              # core library against the Python
make && make -C watermark/c full && python watermark/check_c.py --full CLIP.wav   # with sotto's tracker
make -C watermark/c wasm install                                # docs/watermark.wasm (as c/wasm)
node watermark/check_wasm.mjs [CLIP.wav ...]                     # the page's module under node
```
