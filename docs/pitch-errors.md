# Pitch errors at low rates (2026-11-07)

sotto 400 sends one straight pitch line per 120 ms, so every pitch mistake there is heard for
longer than at 2400. Jeff suggested using the 400 renderings to find the pitch errors and to
fix them in the encoder, where the pitch tracker is shared by every rate.

## The finder

`python tools/pitch_errors.py [--modes track,2400,1200,600,400] [--json OUT]` compares the
pitch each decoder actually plays, frame by frame every 10 ms, against librosa's pYIN
(50-500 Hz) on the same 8 kHz audio. It uses the 16 held-out voices in
`/mnt/project-files/vocoder/samples-clean/` and counts only frames above -40 dBFS that pYIN's
HMM calls voiced.

| Count | Meaning |
|---|---|
| gross | more than 1.6 times off (octave-type) |
| off20 | more than 20% off (the usual gross pitch error, GPE) |
| cents | RMS error of the rest |
| miss / false | voicing disagreements |

It lists the worst runs as time indexes. pYIN isn't ground truth. It sits at its 50 Hz floor
on creaky ends of phrases, and its voicing calls at 8 kHz are loose, so the miss and false
counts are only a guide. A listed spot is a place to listen, not a verdict.

## What it found

Off by more than 20%, out of 8,800 voiced frames:

| | tracker | 2400 | 1200 | 600 | 400 |
|---|---:|---:|---:|---:|---:|
| before | 247 | 243 | 275 | 356 | 472 |
| after the two fixes below | 247 | 243 | 259 | 285 | 296 |
| gross (1.6x), before → after | 151 | 152 | 157 → 146 | 210 → 157 | 206 → 141 |

Before the fixes, sotto 400 almost doubled the tracker's errors. Two encoder bugs caused most
of the extra.

**1. At voice onsets the low rates coded the silence's pitch.** A 20 ms frame whose first half
is unvoiced and second half voiced (voicing code 3, an onset edge) took its pitch from the first
half. That pitch is whatever Codec 2 guessed in the silence, often its 50 Hz floor. The 2400
decoder never plays it, because it takes the next frame's pitch for that half. The low rates
code it, though:

- sotto 1200's B frames interpolate from it;
- the 600 / 400 line fit counts it as a voiced frame, so one onset bends a whole 80 or 120 ms
  pitch line.

Examples in sotto 400:

| Voice | Time | What happened |
|---|---|---|
| LibriSpeech 3536 | 0.63 s | 160 Hz for a 364 Hz voice |
| LibriSpeech 251 | 11.42 s | 136 Hz for 202 Hz |
| LibriSpeech 8842 | 5.94 s | 68 Hz for 222 Hz |
| EARS p051 | 1.94 s | 143 Hz for 219 Hz |

Fix (`Sotto1200.ONSET_WO`, `c/sotto.c emit`): an onset edge codes its voiced half's pitch. The
2400 frame is unchanged, and so are the decoders and the bitstream format.

**2. One wrong frame bent the whole pitch line.** The 600 / 400 line is a least-squares fit, so
a single octave slip pulls every frame of the superframe. Examples:

| Voice | Time | What happened |
|---|---|---|
| LibriSpeech 251 | 6.38 s | 182 Hz for 95 Hz over 9 frames |
| LibriSpeech 251 | 4.14 s | 204 Hz for 97 Hz |
| LibriSpeech 6313 | 4.67 s | 388 Hz for 256 Hz |

Fix (`SottoVLR.OUTLIER = 20`, `c/sotto_vlr.c`):

- A voiced frame more than 20 index steps (about half an octave) off the line is left out, and
  the line is refitted, when at least 2 frames remain.
- In the line search, each frame's error is capped at the same 20 steps.

Smaller thresholds (6 and 10 steps) cut into real pitch movement and scored worse.

### Scores

Scored on the same 16 voices, with the Python encoder and decoder.

| | 2400 | 1200 | 600 | 400 |
|---|---|---|---|---|
| PESQ-NB / ESTOI before | 2.937 / .817 | 2.578 / .762 | 2.096 / .690 | 1.826 / .637 |
| after | 2.937 / .817 | 2.608 / .763 | 2.133 / .692 | 1.861 / .641 |
| hiss variants before (`tools/eval_lr_hiss.py`, `tools/eval_vlr_hiss.py`) | | 2.517 | 2.094 | 1.828 |
| hiss variants after | | 2.544 | 2.113 | 1.854 |

The hiss scores are PESQ-NB from the 16 kHz eval scripts, whose plain 1200 row went from 2.545 to
2.565. Most of the gain is the onset fix (+0.03 at every low rate). The line fix adds +0.016 at 600.

C is bit-exact with Python, as before:

- `tools/check_vlr.py`: 600 99.91%, 400 99.93%.
- `tools/check_lr.py`: 1200 99.6%.
- `tools/check_lr_hiss.py` and `tools/check_vlr_hiss.py`: 99-100%.

The remaining misses are the fixed-lag tracker's, as before. The hiss encoders (`c/sotto_hiss.c`)
take the low rates' pitch from the 2400 frame bits, so they patch an onset frame's pitch bits from
the core (`onset_wi`), as the Python hiss classes inherit `Sotto1200.params`.

The browser page's `docs/sotto.wasm` was rebuilt with the new encoder. Its stored sample renders
(`docs/samples/v38/`) are still from the old encoder, so `make -C c/wasm check` reports the hiss
encoders as differing from them until those are re-rendered.

## Creak at phrase ends (2026-11-08)

Jeff heard the K6 play LibriSpeech 198 (the hiss bench's female clip) at sotto 400 and
reported pitch trouble on "go by all means, my dear". On the K6, the same clip was "much
better" at 1200, and 600 "isn't bad". His read was that the coarse pitch coding gets stuck on
vocal fry.

This first fix went to the clip's last phrase, "Miss Tilney always wears white" (11.9-13.9 s),
taken at first for Jeff's phrase. Jeff confirmed that it sounds better there. His phrase is
earlier, at 9.0-10.3 s. The next section covers it.

The slip at 13.3 s is on "white". The voice goes creaky at the end of the vowel, and then into
fry (pYIN 60-67 Hz). The tracker reads the creak as 89-96 Hz, half the voice's 165 Hz. One
120 ms superframe held the last modal frame (165 Hz, full level) and four creak frames. The
line fit went with the majority, and the outlier rule then dropped the modal frame. So 400
played 91 Hz on the vowel and a steady 94-105 Hz buzz, rising, for 120 ms. 1200 plays 165 Hz to
the end of the vowel and then 80 ms of the creak.

| 13.32-13.42 s | modal | creak | creak | creak | creak | (unvoiced) |
|---|---:|---:|---:|---:|---:|---:|
| tracker | 165 | 89 | 93 | 96 | 96 | |
| sotto 400 before | 91 | 94 | 96 | 100 | 101 | 105 |
| sotto 400 after | 157 | 138 | 119 | 103 | 89 | 79 |

Fix (`SottoVLR.creak_mask`, `CREAK_*`; `c/sotto_vlr.c` `creak_step`). Encoder only, so the
bitstream and every decoder, the K6's included, are unchanged.

- A voiced frame is a **creak frame** when it sits at least 25 index steps (about 0.65 of an
  octave) below the voiced frame just before it. That frame and the one before it must both be
  fully voiced and within 6 steps of each other. The following voiced frames stay creak while
  they're 20 or more steps below that steady pitch.
- In a superframe holding both creak and modal frames, a creak frame weighs 1 in the line fit
  and the search, against 4 for a modal frame. The outlier rule is skipped there, and the
  search tries every centre.
- So the line keeps the modal frame and falls into the creak as far as the slope table
  reaches, as a voice falls at a phrase end.
- A superframe that is all creak is coded as before.

The steadiness checks matter. Without them, an onset's junk pitch (LibriSpeech 251 at 6.38 s:
500 Hz on an onset edge, then 96 Hz) made the real voice after it look like creak, and 400
played 349 Hz there. Likewise, the mixed-voicing onset frames before true 62 Hz fry
(LibriSpeech 3081 at 10.68 s) turned the fry into a glide from 247 Hz.

On the 16 voices (`tools/pitch_errors.py --modes 600,400`; no voice got worse):

| | 600 off20 | 600 gross | 400 off20 | 400 gross |
|---|---:|---:|---:|---:|
| before | 285 | 157 | 296 | 141 |
| after | 270 | 151 | 281 | 137 |

The gains come from EARS p020 and p070, whose voices go creaky or get halved by the tracker mid-run.
PESQ-NB is flat (600 2.1328 → 2.1323, 400 1.8609 → 1.8669; ESTOI 0.692 / 0.641 both). Only
three voices change at all, so this is a rare event that is loud when it happens.

The C encoder matches the Python.

- `tools/check_vlr_hiss.py`, on the 16 voices plus LibriSpeech 198: every superframe matches,
  2,422 of 2,422 at 600 and 1,616 of 1,616 at 400.
- `tools/check_vlr.py`: 99.92% and 99.94%. The only misses are the same EARS p051 frames as
  before the change, which come from the fixed-lag tracker.
- C encoder into C decoder, PESQ-NB: 600 2.114 → 2.118, 400 1.842 → 1.857.

`docs/sotto.wasm` was rebuilt, since the page's 600 / 400 encoders are this C code. LibriSpeech
198's 400 stream changes in one superframe, the one holding "my".

## "All" two semitones flat: the centre search (2026-11-08)

A speech recogniser (pocketsphinx) puts Jeff's phrase "go by all means, my dear" at
9.03-10.29 s. "Go" and "by" are within about 90 cents at 400. "All" (9.48-9.58 s) was 150-190
cents flat: 225 falling to 206 Hz, where the voice is at 242 falling to 229 Hz.

"All" starts with a creaky glottal onset. The tracker reads its first frame (9.48 s) at
117 Hz, against 242 Hz for the rest. That frame sat 19.5 index steps under the least-squares
line, just inside `OUTLIER` (20), so it stayed in the fit and pulled the line's centre down.
The search then tried only the fit's centre ±1. The line the capped error actually wants
(centre about 85, running through the other five frames) was 5 steps away and never tried.

Fix (`SottoVLR.FULL_SEARCH`; `c/sotto_vlr.c`, always on). The search tries all 128 centres
with all 8 slopes, about 6,000 small sums a superframe. Equal errors go to the centre nearest
the fit. This keeps one-frame superframes flat instead of on the steepest slope that happens
to hit the frame. "All" now plays 251, 247, 242, 238, 233 and 229 Hz against the voice's 242
to 229 Hz.

On the 16 voices, creak fix included (`tools/pitch_errors.py`):

| | 600 off20 | 600 gross | 400 off20 | 400 gross |
|---|---:|---:|---:|---:|
| main before PR #134 | 285 | 157 | 296 | 141 |
| creak fix (#134) | 270 | 151 | 281 | 137 |
| plus the full search | 236 | 136 | 246 | 120 |

PESQ-NB over the creak fix: 600 2.1323 → 2.1462, 400 1.8669 → 1.8803. ESTOI: 0.6922 → 0.6925
and 0.6407 → 0.6433. Per voice, PESQ moves by up to ±0.1, more of it up than down: at 400,
11 voices gain and 5 lose (worst EARS p020 −0.058, best 3536 +0.063); at 600, 10 gain and 6
lose (worst 777 −0.081, best EARS p100 +0.114). PESQ isn't a pitch measure, and the pitch
counts improve on most voices.

## Sub-octave runs: the fold (2026-11-19)

**The problem.** The tracker played some female voices at half or a third of their pitch for a
few frames in breathy or rough stretches. About 140 tracker frames were affected:

| Voice | Time | Tracker | pYIN |
|---|---|---|---|
| EARS p070 | 0.82-0.94 s | 166 Hz | 334 Hz |
| EARS p070 | 8.06-8.19 s | 85 Hz | 171 Hz |
| EARS p070 | 8.44-8.54 s | 108 Hz | 214 Hz |
| EARS p051 | 6.35-6.46 s | 76-100 Hz | 227 Hz |
| EARS p051 | 3.77-3.83 s | 108 Hz | 200 Hz |
| LibriSpeech 3536 | 1.64 s | 82 Hz | 262 Hz |

There are two kinds:

- **Period doubling** (p070 at 8.1 s): the waveform really repeats every second cycle. The
  normalised autocorrelation is 0.93-0.97 at twice the period and only 0.55-0.8 at the period.
  So a comb at half the pitch fits better, by 1-2 units of MBE fit error, but listeners hear the
  higher pitch. Codec 2's own estimate is right here, and the tracker overrules it.
- **Creak** (3536 at 1.6 s): the stretch is barely periodic (autocorrelation under 0.4 at every
  candidate). Codec 2 and the tracker both sit near a third of the pitch, so no candidate is
  near the true one.

The odd/even sub-octave check doesn't fire in either case, because the odd harmonics of the
half pitch are only 0-2 dB down, not the 10 dB it looks for.

**What didn't work.** A time-domain cost in the tracker, `track_pitch_voicing(up=4,
up_thr=0.65)`, cut octave-low frames from 142 to 97 and left PESQ flat. In the blind pitch-pairs
round (2026-11-07 page, unblinded 2026-11-19) it won nothing: one loss (p070 0.82 s) and three
ties. It stays off and has no C port.

**The fold** (`sinusoid.fold_subharmonics`, on in the v3.7 and v3.8 encoders since 2026-11-19).
After the tracker decides each frame, a run starts at a voiced frame whose pitch is at most 0.62
of the voiced frame before it (one unvoiced frame between is allowed). The run takes k = 2 or 3
(the nearer of anchor / pitch). It lasts while the frames stay voiced, for at most 12 frames,
with no jump up of more than 1.3 times from frame to frame, and with k times the pitch within
1.5 times of the anchor. Each frame in the run then gets one of these:

- k times its pitch, refined, when the speech still repeats at that period (autocorrelation
  0.45 or more);
- otherwise the anchor's pitch, refined, when even its own period is weakly periodic
  (autocorrelation under 0.5, creak);
- otherwise no change.

The fold is causal, so the streaming C encoders apply it as they decide frames, with no extra
delay. Voicing is unchanged.

- **sotto 400, 16 voices, against pYIN:** gross errors fell from 120 to 99 and frames off by
  20% from 246 to 201. p070 went from 47 to 15, 3536 from 16 to 6 and p051 from 21 to 15. Male
  voices didn't change. On 3081's creaky phrase end (10.7 s) the fold plays about 195 Hz where
  pYIN hears about 62 Hz creak, so that clip's count rose from 59 to 66.
- **PESQ-NB, 16 voices:** 2400 2.943 to 2.939, 1200 2.608 to 2.612, 600 2.146 to 2.146 and
  400 1.880 to 1.878. These are ties.
- **Listening round 22** (sotto 400, 9 pairs, 2026-11-19): the fold won 4 with no losses and 4
  ties, and the null pair was called correctly. The wins were p070 8.1 s, 3536 1.6 s, p070
  0.8 s and 3081 3.0 s. The 3081 creaky end was a tie. Key and scripts are in the project
  folder (`vocoder/listening/ab22/`).
- **C:** the float encoder (`c/sotto.c`, `SOTTO_FOLD`) is bit-exact with Python on p070, 3536
  and 3081 (p051 99.7%, the same as before the fold). The fixed-point encoder
  (`c/fixed/sotto_fx_enc.c`) refines on its kept 16-bit spectrum and runs the autocorrelation
  tests at 15-bit precision. It matches the float encoder on 96.4% of frames (97.0% before),
  and it keeps the last (LAG + 2) x 80 + 240 samples, 2,080 bytes more state.
  `-DSOTTO_FOLD=0` gives the encoder before.

## A strong fundamental skipped: the low band (2026-11-21)

Jeff listened to all 28 English Kokoro TTS voices through sotto 1200 and heard many pitch
errors, worst on af_nicole (a whispery voice) and on bm_george and bm_lewis. Against pYIN, the
tracker played Nicole at about 430 Hz where she speaks at about 150 Hz: 1,334 of her 1,962
voiced frames were off by more than 1.6 times. The fold (above) has nothing to do with it:
turning it off changes almost nothing.

**Cause.** `sinusoid.fit_error` sums the residual over the harmonic bands of a candidate
(band l spans (l - 1/2) to (l + 1/2) times its pitch), but divides by the energy from bin 1 up.
The energy below the first band is in neither the residual nor any fitted harmonic, so it
counts as explained. Nicole's voice is almost a pure fundamental with noise above it. A
candidate at three times her pitch starts its first band above her fundamental, skips it, and
fits for free: its error came out lower than the true pitch's.

**Fix (v3.10 encoder).** `track_pitch_voicing(low_rank=True)` (`vocoder_lab.LOW_RANK`, on in
"tracked4"): each candidate also pays log(fit error with the energy below its first band
counted as residual / fit error without it), less the smallest such term among the frame's
candidates. It only ranks candidates against each other, so the best candidate's cost and the
voicing decision stay as they were. Counting the low band in the cost outright fixed the pitch
as well, but unvoiced many male frames (the first harmonic's main lobe reaches below half its
pitch), costing up to 0.19 PESQ on low male voices. The band starts at bin 2 (31 Hz,
`LOW_BIN0`), so DC offset and rumble don't count, and the residual is floored at 2^-20 of the
band energy so near-silent frames agree between float and fixed point.

- **pYIN gross errors (> 1.6x), tracker:** Nicole 1,334 to 67 (26 sentences), George 178 to 2,
  Sarah 14 to 1; Lewis unchanged at 58. The 16 usual voices (`vocoder/samples-clean`): 112 to 79.
- **PESQ-NB (Python, plain sotto 1200 / 400):** 31 usual voices (samples-clean, samples15,
  samples-sc) 2.784 to 2.793 / 2.094 to 2.094; the 28 Kokoro voices 2.496 to 2.569 / 1.810
  to 1.833 (Nicole +0.50, Eric +0.56, George +0.35 at 1200).
- **Listening round 23** (sotto 1200, 10 pairs, 2026-11-21): the fix won its one real pair
  against today's encoder (am_eric). The render script leaked one variant's settings into the
  next render, so pairs 1, 5, 8 and 10 (Nicole, George, LibriSpeech 777, EARS p025), keyed as
  against the old encoder, were the fix twice or the fix against the NCCF option; Jeff called
  them all no difference. Round 25 redoes them.
- **The K6's slim encoder** (`c/fixed/sotto_fx_slim.c`) finds pitch in the time domain and
  never had this bug (Nicole 8, George 1, Lewis 6 gross frames). Feeding slim's pitch track
  into the reference coder scored below the fix (2.770 / 2.537 at 1200). One time-domain
  candidate per frame in the reference tracker (`tdc=1`, the shortest-lag NCCF peak within 0.9
  of the highest) fixed Lewis (58 to 1) but split round 23 (1 win, 1 loss, 3 ties against the
  fix), so it stays off (`vocoder_lab.TDC = 0`).
- **C:** `c/sotto.c` `SOTTO_LOW_RANK` (bit-exact with Python on Nicole and LibriSpeech 652,
  p051 99.8% as before); `c/fixed/sotto_fx_enc.c` matches the float encoder on 97% of frames,
  as before. `-DSOTTO_LOW_RANK=0` gives the encoder before.
- **Goldens:** frames moved on both golden voices. Float-decoder PESQ at 2400 / 1200 / 600 /
  400: female libri198 2.165 to 2.262, 2.082 to 2.078, 1.796 to 1.813, 1.536 to 1.541; male
  libri3436 2.779 to 2.723, 2.568 to 2.506, 2.219 to 2.280, 1.863 to 1.867. Plain 2400 male went
  3.18 to 2.96 on its 6 s golden cut; Python v3.7 on the whole 15 s clip goes 3.330 to 3.343,
  and the tracker's changes there are a few quiet background frames and a one-frame onset.
- **Hiss burst test** (`test_hiss_no_bits_frames_stay_level_in_background_hiss`): the new
  encoder starts kristoff's voiced onset at 4.1 s, as on the clean clip, and the sotto 400
  hiss cap then holds the burst to 7.5 dB (it was 4.4). Over other clips and noise seeds the
  old encoder already reached 6.4-7.9 dB, so the bound is now 8 dB.

- **Sub-octave check from the first harmonic** (`vocoder_lab.SUB_FIRST = 1`, `c/sotto.c`
  `SOTTO_SUB_FIRST`): Nicole's "seven" (01.wav 2.30-2.38 s) and "from" (05.wav 3.40-3.48 s)
  dropped to half pitch, where a comb at half the pitch fits the breathy noise between
  harmonics and the odd/even test, starting at the 3rd harmonic, missed the gap at the 1st.
  Starting at the 1st: Nicole 67 to 43 gross frames, samples-clean 79 to 71, PESQ 1200 usual
  2.793 to 2.785, tts 2.569 to 2.571; 400 flat. C bit-exact with Python on Nicole 01, 05 and
  libri3436; fixed point matches float as before. `-DSOTTO_SUB_FIRST=3` gives the encoder before.
- **Listening round 24** (9 pairs): `SUB_FIRST = 1` won both pairs against the same encoder
  without it (Nicole "seven", "from"). The same render bug made pairs 3, 7, 8 and 9 one version
  twice, so moving the low band's start to 47 Hz (`LOW_BIN0 = 4`, against 31-47 Hz rumble that
  pushed EARS p025's "s" at 1.62 s to 430-500 Hz) was never heard on its own. On Nicole 04 it
  voices quiet gaps at ~100 Hz and halves the pitch at 2.9 s, and the pair that carried both
  changes lost to 31 Hz. It stays at 31 Hz until round 25.

Left for later: the creak at a word's end. Kokoro af_sarah's "foxtrot" word unit (TTS corpus,
"kilo. foxtrot, papa.") ends at 1.48-1.53 s with the period falling apart (NCCF under 0.5);
every variant voices it at 127, 115, 112 Hz where it was 180 Hz, an octave drop on the ear.
af_heart 01 at 2.43-2.5 s is the same kind.

## Still open

**Creaky phrase ends.** In LibriSpeech 3081 at 9.5-11 s, pYIN hears 60-65 Hz creak and sotto
plays 115-260 Hz. pYIN's floor makes this one hard to judge without ears.
