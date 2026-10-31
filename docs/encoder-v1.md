# sotto encoder v1 and v2: pitch, voicing and quantizer experiments

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

*These numbers used the old per-clip alignment; corrected numbers, with v2, are in the v2 section below.*

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

## v2: pitch and voicing tracked together (2026-10-31)

The first club listening test (two listeners) found no preference for band voicing. It did find a "springs / glorp" sound in v1 on the female voice at 6 to 7 s. Two causes:
- She goes above 420 Hz there, past Codec 2's 400 Hz pitch ceiling.
- Frames in a quiet transition were called voiced with a pitch wandering between 50 and 300 Hz.

v2 (`SottoV2`, `sinusoid.track_pitch_voicing`) runs one Viterbi search over the whole utterance. Each frame can be unvoiced, or voiced at one of these candidate pitches: Codec 2's estimate for this frame or its neighbours, times 1, 2 or ½, each refined. The costs are:
- the MBE fit error, as in v1;
- a penalty for disagreeing with Codec 2's voicing decision;
- a penalty for switching between voiced and unvoiced;
- a penalty for a pitch jump, steeper above a third of an octave.

The 7-bit pitch field now spans 50 to 500 Hz. Re-checking Codec 2's voicing test at the corrected pitch, without the joint search, unvoiced too much (female 2.68 to 2.55) and was dropped. Normalising the fit error by its value on white noise, instead of the fixed bias toward higher pitch, scored the same and is left as an option (`norm="noise"`).

### Scoring fix

The scripts used to find each clip's delay by waveform correlation. Codecs with synthetic phase barely follow the input waveform, so that search picked lags from 50 to 180 samples. That pulled ESTOI down by up to 0.1 and moved PESQ by up to ±0.1. ESTOI peaks at a 150 to 170 sample delay for Codec 2 and every sotto encoder, so scoring now uses a fixed 160 (`audio_race.CODEC_DELAY`). ESTOI figures in earlier write-ups (audio-race.md, encoder-v0.md) are understated. Their rankings hold.

### Encoder against encoder, corrected alignment

The chain is the same as above. Each cell is the mean of 3 seeds, shown as PESQ (ESTOI):

| Condition | Codec | Female | Male (LibriSpeech) | Male (ve9qrp) |
|---|---|---:|---:|---:|
| No radio channel | Codec 2 2400 | 2.21 (0.74) | 2.94 (0.75) | 2.78 (0.74) |
| | sotto v0 | 2.51 (0.72) | 3.13 (0.84) | 2.92 (0.75) |
| | sotto v1 | 2.65 (0.77) | 3.20 (0.85) | 2.87 (0.76) |
| | **sotto v2** | **2.91 (0.79)** | **3.21 (0.85)** | **3.00 (0.76)** |
| 446 MHz 60 km/h, 52 dB-Hz | Codec 2 2400 | 1.69 (0.67) | 2.30 (0.70) | 2.48 (0.71) |
| | sotto v0 | 2.11 (0.70) | 2.67 (0.82) | 2.76 (0.74) |
| | sotto v1 | 2.27 (0.75) | 2.78 (0.83) | 2.61 (0.75) |
| | **sotto v2** | **2.44 (0.77)** | **2.91 (0.84)** | **2.78 (0.75)** |
| 446 MHz 60 km/h, 56 dB-Hz | Codec 2 2400 | 2.21 (0.74) | 2.73 (0.74) | 2.75 (0.74) |
| | sotto v0 | 2.45 (0.72) | 3.07 (0.84) | 2.89 (0.75) |
| | sotto v1 | 2.63 (0.77) | 3.11 (0.84) | 2.83 (0.76) |
| | **sotto v2** | **2.86 (0.79)** | **3.12 (0.85)** | **2.98 (0.76)** |
| 146 MHz 30 km/h, 56 dB-Hz | Codec 2 2400 | 1.82 (0.67) | 2.06 (0.67) | 1.98 (0.67) |
| | sotto v0 | 2.19 (0.70) | 2.65 (0.82) | 2.30 (0.73) |
| | sotto v1 | 2.26 (0.75) | 2.65 (0.82) | 2.20 (0.74) |
| | **sotto v2** | **2.51 (0.77)** | 2.61 (0.82) | **2.30 (0.74)** |

- **v2 is best or tied in every condition except one.** At VHF, LibriSpeech male scores 2.61 against 2.65, which is within noise.
- **Against Codec 2, the female voice gains +0.6 to +0.75 PESQ** and all three voices gain in ESTOI. The male LibriSpeech ESTOI gain is large: 0.75 to 0.85 with no channel.
- **The female voice is now within 0.1 to 0.3 of the men** (it was 0.7 behind with Codec 2), so most of her gap was pitch and voicing errors.
- The predictive variant from above was not rescored.

A second blind listening test (v1 against v2, and Codec 2 against v2) is with the club. The listening page now pairs Codec 2 with v2.

### Listening round 2 (first answers)

Jeff's answers: v2 beat v1 in 3 of the 4 pairs, with the fourth a tie, and won the pair on the old "glorp" passage. Against Codec 2, v2 won on the female and the LibriSpeech male. On ve9qrp it lost a close call: v2 "had better bottom end", but Codec 2 "had a little bit more pleasant silence". Measured in that clip's pauses, v2's background is as loud as the original but brighter, 5 to 6 dB above Codec 2 at 3 to 4 kHz.

`soften_pauses` (a `SottoV2(quiet=...)` option, off by default) is a decoder-only fix. It gives unvoiced frames well below the recent speech peak a high-frequency roll-off. At a 20 dB margin and 6 dB/octave above 1 kHz it is PESQ-neutral. It goes into the next listening round before becoming the default.

### Predicted envelope with resets (`SottoV2P`)

Jeff suggested coding the envelope's change between frames, since articulators move at bounded speed (the idea behind IMBE/AMBE's predicted amplitudes and Atal's temporal decomposition). To stop channel errors carrying over, the predictor resets on frames where both 10 ms halves are unvoiced. `SottoV2P(every=N)` adds a forced reset every N frames. Reset frames use v2's memoryless quantizer, and the others use one trained on prediction residuals. The bit layout is unchanged, and the decoder holds the predictor on CRC-failed frames.

PESQ, female / male LibriSpeech / ve9qrp, mean of 3 seeds:

| Condition | v2 (memoryless) | resets on unvoiced only | + every 10 frames |
|---|---|---|---|
| No radio channel | **2.91** / 3.21 / **3.00** | 2.83 / 3.21 / 2.94 | 2.84 / **3.25** / 2.94 |
| 446 MHz 60 km/h, 52 dB-Hz | **2.44 / 2.91 / 2.78** | 2.26 / 2.58 / 2.64 | 2.25 / 2.72 / 2.73 |
| 446 MHz 60 km/h, 56 dB-Hz | **2.86** / 3.12 / **2.98** | 2.80 / **3.13** / 2.87 | 2.80 / 3.06 / 2.90 |
| 146 MHz 30 km/h, 56 dB-Hz | **2.51** / 2.61 / 2.30 | 2.39 / 2.57 / 2.29 | 2.38 / **2.72** / **2.35** |

- **The resets work.** At UHF 52 dB-Hz the loss against memoryless is now 0.05 to 0.2, about half what plain prediction lost before (v1: 0.1 to 0.26). The forced reset every 10 frames helps further on the men.
- **Prediction itself gains nothing yet.** Even with no channel, the predicted variants are within ±0.08 of v2. With this 34-bit scalar DCT quantizer, coding a residual is no cheaper than coding the frame. Resets are on 12 to 48% of frames (more for ve9qrp, which pauses more).
- **Next:** revisit with a trained vector quantizer, where prediction does pay off in AMBE. The resets and the CRC hold make it safe to try.

## More voices, and v3 (trained vector quantizer)

### Speech Commands voices

LibriVox, Wikimedia, OpenSLR and Hugging Face are blocked from the sandbox. Google's Speech Commands v0.02 (Warden 2018, CC BY 4.0) is reachable: one-second words from about 2,600 volunteers. Test clips: speakers who said all ten digits were joined into "zero ... nine" clips of 8 to 12 s, and 12 clean ones were kept, 6 lower voices and 6 higher. Two of the higher voices are around 380 to 390 Hz. These 12 speakers are excluded from all training. The clips and their scores are in the project folder, and `tools/sc_counting_clips.py` builds them.

### Club listening rounds 3 and 4

Round 3 (Jeff and Andrew) put v2 against Codec 2 on 8 of the new voices. v2 won 9 of the 16 answers, Codec 2 won 7. Both listeners picked Codec 2 for the very high voice (390 Hz) and a very low one (80 Hz), and both picked v2 on three mid-range voices. PESQ favoured v2 on every pair, so the pitch-range edges are where ears and PESQ disagree. The pause softening drew "no difference" or a preference for plain v2, so it's dropped. Jeff also heard v2 put a faint floor in the gaps between words. v2's lowest energy code plays about −80 dBFS of noise, while Codec 2 goes to −95. A crackle after "th" came from fricative frames called voiced at a junk low pitch. Normalising the pitch fit by its value on noise fixes "three" but not "six", so that is still open.

### v3

`SottoV3` keeps v2's frame layout. Two changes:
- **The 34 shape bits are a 3-stage vector quantizer (12 + 11 + 11 bits) with M-best search (M = 8).** It is trained on 184,000 frames from 600 Speech Commands speakers (300 above and 300 below 165 Hz median pitch) plus Codec 2's recordings. `tools/sc_corpus.py` and `tools/train_shape_vq.py` build it, and it is stored in `sim/data/shape_msvq_34.npz` (0.6 MB). On held-out frames it has 45% less envelope error than the scalar quantizer retrained on the same data (2.54 against 4.66 dB²).
- **Energy code 0 decodes as true silence.**

No radio channel, 15 voices (`docs/results/clean_15voices.json`), mean PESQ (ESTOI):

| Codec 2 | v2 | v2, scalar retrained on the new data | **v3** |
|---:|---:|---:|---:|
| 2.84 (0.73) | 3.19 (0.77) | 3.20 (0.78) | **3.27 (0.79)** |

v3 beats v2 on 12 of the 15 voices. Over the radio channels it ties v2 on average (PESQ 2.72 for both over 9 condition × voice cells). It is up to +0.12 on the men and down 0.15 on the female at UHF 52 dB-Hz. ESTOI is equal or better in every cell. The female loss may come from the mute after three lost frames, which is now true silence rather than faint noise.

Round 4 (one listener so far). v3 beat Codec 2 on 3 of 4 counting voices, including the 80 Hz voice that Codec 2 won in round 3. Codec 2 again won the 390 Hz voice. That voice was recorded on a heavily band-limited microphone, and the listener judged v3 the closer match to the original, so future rounds put the original next to every pair. v3 against v2 was a tie in all five pairs, with and without the channel. The null pair was called a tie. Since v3 never lost to v2 by ear and scores higher clean, the public listening page now uses v3.

Both v2 and v3 have a fault on "five" ("five-anuh", or a reverb tail). The final /v/ is a voiced fricative: the low harmonics are clean, but above 1 kHz the harmonic fit SNR is only 2 to 4 dB. Binary voicing renders it as a fully voiced vowel. On one voice the tracker also follows it down to about 100 Hz and keeps it voiced for 200 ms as it fades to -80 dB. Mixed (band) voicing on fricative tails, or ending the voiced run once the high-band fit collapses, is the next thing to try.

### Voiced fricatives: v3.1 and v3.2

Listeners heard "five-anuh" and a reverb-like tail on "five" in both v2 and v3. Round 5 tested two fixes against v3, with the original playing next to every pair (one listener; null pair called correctly):

- **tail**: voiced frames whose harmonic fit below 1 kHz is weak (mean per-harmonic SNR under 6 dB) and that sit more than 20 dB below the loudest frame of the last 300 ms are sent as unvoiced. It needs no new bits. Preferred on one "five", tied on four other pairs.
- **mix**: voiced frames with a weak low-band fit (under 8 dB) are synthesised with harmonics only below 1 kHz and noise above. Preferred on two pairs, including the other "five", tied on two.

Neither lost a pair. PESQ calls both even with v3 (3.26 against 3.27 over 15 voices).

**v3.1** (`SottoV31`) puts the tail rule in the encoder (`sinusoid.unvoice_tails`). It uses the same frame and decoder as v3. PESQ over 15 voices is 3.27 (v3: 3.27). Over the channels it is level on average: female UHF 52 dB-Hz is 2.53 against 2.29, LibriSpeech male 2.85 against 3.02. Those are within the run-to-run spread of the fading channel.

**v3.2** (`SottoV32`) sends mixed excitation without new bits. The two voicing bits become one code per 20 ms frame: U U, V V, M M, or an edge (one half unvoiced, the other mixed). An edge's order follows the previous frame: after an unvoiced half it is an onset. Plain U V and V U edges are only about 1% of frames and become U M and M U. V M and M V (about 9%) are sent as V V. PESQ over 15 voices is 3.25, against 3.27 for v3.1. Round 6 compares the two by ear.

Round 6 (one listener, original in every pair): v3.2 was preferred on 2 of 10 pairs (the female clip from 6 s, and the voice with the "th" crackle), and the other 8 were ties. The null pair was called correctly.

**v3.3** (`SottoV33`) fixes a "grumbly" word the listener found on the null pair. On "two" from one higher voice, the tracker chose 129 Hz where the pitch is 258 Hz: the breathy vowel fits better with twice as many harmonics. At the half pitch, the odd harmonics (from the 3rd up) sit 18 to 28 dB below the even ones. `sinusoid.odd_even_db` measures that, and the tracker now adds 2 per 10 dB below -10 dB to such a candidate. Over 15 voices that changes "two" to 258 Hz and gives PESQ 3.26 (v3.2: 3.25). Over the channels it is level with v3.2 or slightly up (female 2.38-2.86 against 2.38-2.78, LibriSpeech male 2.66-3.29 against 2.68-3.24).

The remaining "anuh" on one voice is partly the formant postfilter. In the "v" of "five" it cuts 1 to 2 kHz by 6 to 10 dB, which makes the frication sound nasal. Unquantized synthesis keeps that band. Weakening the postfilter on quiet or mixed frames restores the band but costs 0.06 to 0.1 PESQ everywhere, so it is parked.

## Cleaner speech: LibriSpeech and EARS (v3.3 codebook)

The listener pointed out that the Speech Commands clips are phone-microphone recordings of single words. Two cleaner corpora were added:

- **LibriSpeech dev-clean** (CC BY 4.0, 40 speakers).
- **EARS** (Meta, 2024; 107 speakers, anechoic studio, read and conversational speech). Its CC BY-NC 4.0 licence rules it out for anything shipped in this repository.

`tools/clean_corpus.py` holds out 8 speakers from each corpus, half female and half male. It writes one untrimmed 12 s clip per held-out speaker, and builds training shapes from the other speakers: up to 240 s each for 32 LibriSpeech speakers and 120 s each for 99 EARS speakers. Three codebooks were trained with `tools/train_shape_vq.py` and scored with v3.3 on the 16 new voices and on the earlier 15:

| codebook | training frames | LibriSpeech 8 | EARS 8 | earlier 15 |
|---|---|---|---|---|
| Codec 2 2400 (reference) | | 2.43 | 2.25 | 2.84 |
| Speech Commands (v3) | 0.19 M | 2.88 | 2.80 | 3.26 |
| + LibriSpeech | 0.48 M | 2.88 | 2.84 | 3.27 |
| + LibriSpeech + EARS | 0.93 M | 2.89 | 2.81 | 3.27 |

PESQ, no channel. Full results are in `docs/results/codebook_eval.json`.

- **sotto against Codec 2 on unseen voices:** v3.3 beats Codec 2 on all 16 new voices, by 0.45 PESQ on LibriSpeech and 0.56 to 0.59 on EARS.
- **More data helps a little:** adding LibriSpeech cuts the shape error on the new voices by 7 to 8% (2.23 to 2.06 dB² on LibriSpeech, 2.17 to 2.02 on EARS). PESQ moves up by up to 0.035.
- **EARS adds nothing useful:** it lowers the in-domain shape error further but doesn't improve PESQ.

The shipped codebook (`sim/data/shape_msvq_34.npz`) is now the Speech Commands + LibriSpeech one. Its training data is CC BY only, so EARS is used only for testing.

## Lost frames on 2 m: decoder concealment (v3.4)

Until now the receiver handled a lost frame (CRC failure) by repeating the last good frame's bits up to three times (60 ms) and then sending a mute frame. Replaying a voiced frame holds a steady buzz, which is the "springs" that listeners report on fading digital voice. The mute then cuts to silence.

**v3.4** (`SottoV34`) moves concealment into the decoder, which receives the CRC flags. A lost frame reuses the last good frame's parameters. The level falls `slope` dB per 20 ms after the first lost frame. Voiced frames turn mixed (harmonics below 1 kHz, noise above) from the second lost frame on. After `max_lost` frames the output is silent until a good frame arrives.

The sweep in `tools/conceal_sweep.py` covers 146 MHz at 5, 30 and 60 km/h and 52 and 56 dB-Hz, with 7 voices and 3 fading seeds. Mean frame loss is 8.5%; the worst case, 5 km/h at 52 dB-Hz, loses 16%. Mean PESQ:

| decoder | PESQ |
|---|---|
| Codec 2 2400 (receiver repeat, then mute) | 1.70 |
| v3.3 (receiver repeat, then mute) | 2.24 |
| v3.4, 3 dB/frame, mixed from frame 2, silent after 8 | 2.34 |
| v3.4, 6 dB/frame | 2.30 |
| v3.4, 3 dB/frame, stays voiced | 2.34 |
| v3.4, 3 dB/frame, silent after 4 | 2.31 |
| **v3.4, 2 dB/frame, mixed from frame 2, silent after 15 (default)** | **2.36** |

What the sweep shows:

- **Concealment gains 0.10 to 0.17 at 52 dB-Hz** and 0.05 to 0.10 at 56 dB-Hz.
- **A slow fade beats a quick mute.** The default fades by 28 dB over 300 ms.
- **Mixing has no measurable PESQ effect** (+0.01). It's kept because the held buzz is what listeners complain about.

Listening round 7 (one listener, fading 2 m, original in every pair):

- **Against Codec 2:** v3.4 won all 6 pairs.
- **Against v3.3:** v3.3 won 2 (two men at 30 km/h, weak signal, 13 to 17% of frames lost) and 2 were ties.
- **Why:** the listener described v3.3 as "quietly drops", and v3.4 as continuing the last sound, which makes drops more obvious.
- **Takeaway:** PESQ rewards filling a gap; the ear prefers a short, quiet one. At 30 to 60 km/h, 40% of lost frames come in runs of exactly 5, a whole 100 ms YSF frame, because the code spans all five frames.

`SottoV34` now takes `hold`, the number of lost frames kept at full level. Round 8 compares v3.3 with two short-fade versions: "mid" (hold 3, then 6 dB per frame, silent after 5) and "quick" (hold 2, 6 dB per frame, silent after 4).

Round 8 (one listener, weak-signal 2 m, original in every pair):

- **quick:** won 2, tied 3, lost none against v3.3.
- **mid:** won 2, lost 1, tied 2.
- **Null pair:** called a tie, which is correct.

v3.5's concealment is therefore "quick": it holds a lost frame for 40 ms, fades 6 dB per 20 ms, and is silent after 80 ms. With that, v3.5 scores (female / LibriSpeech male / ve9qrp):

- no channel: 2.90 / 3.36 / 3.09
- UHF 60 km/h, 52 dB-Hz: 2.46 / 2.94 / 2.97
- VHF 30 km/h, 56 dB-Hz: 2.53 / 2.90 / 2.58

Codec 2 scores 2.21 / 2.94 / 2.78, 1.69 / 2.30 / 2.48 and 1.82 / 2.06 / 1.98 in the same conditions. The public listening page now uses v3.5.

**Would unequal protection save part of a lost frame?** A second CRC on the most important bits (voicing, pitch, energy and the first VQ stage) would let the decoder use those bits when the rest of the frame fails. On 2 m fading, the frames that fail CRC almost always fail completely: the median failed frame has 12 to 21 wrong bits out of 48. Only 10 to 20% of failed frames had their first 26 bits intact, and 16 to 34% had their first 14 (voicing, pitch and energy). The losses are deep fades, not scattered bit errors, so a split CRC would recover little. It isn't worth the extra CRC bits.

## Real-time pitch tracking

The joint pitch and voicing tracker searched each whole utterance (Viterbi with full traceback). A real-time encoder can only look a fixed number of frames ahead, so the tracker now has a `lag` option: frame t is decided from the best path at frame t + lag. Mean PESQ over 31 voices (the earlier 15 and the 16 held-out):

| look-ahead | whole utterance | 10 ms | 20 ms | 40 ms | 80 ms |
|---|---|---|---|---|---|
| PESQ | 3.055 | 3.011 | 3.035 | 3.041 | 3.052 |

An 80 ms look-ahead gives up only 0.003, so real-time tracking costs nothing that matters. That adds 80 ms of delay; push-to-talk radio tolerates it. The C port should use lag = 8.

## Postfilter re-tuned (v3.5)

The formant postfilter gain (1.5) was chosen for the scalar quantizer in v0. With the trained codebook, a sweep over 31 voices (no channel):

| gain | 1.0 | 1.2 | 1.35 | 1.5 | 1.7 | 2.0 |
|---|---|---|---|---|---|---|
| PESQ | 2.81 | 3.02 | **3.08** | 3.06 | 2.94 | 2.69 |
| ESTOI | 0.802 | 0.803 | 0.796 | 0.785 | 0.767 | 0.737 |

**v3.5** (`SottoV35`) is v3.4 with gain 1.35. Its shallower valleys also cut less of the 1 to 2 kHz frication that made "five" sound like "five-anuh". Round 7 was rendered before this change, with gain 1.5.

The encoder race (3 voices; v3.4 → v3.5 PESQ) shows v3.5 ahead of v3.4 in every cell:

| condition | female | LibriSpeech male | ve9qrp |
|---|---|---|---|
| no channel | 2.89 → 2.90 | 3.31 → 3.36 | 3.03 → 3.09 |
| UHF 60 km/h 52 dB-Hz | 2.47 → 2.47 | 2.91 → 2.97 | 2.88 → 2.94 |
| UHF 60 km/h 56 dB-Hz | 2.89 → 2.91 | 3.16 → 3.22 | 3.04 → 3.08 |
| VHF 30 km/h 56 dB-Hz | 2.55 → 2.58 | 2.88 → 2.92 | 2.53 → 2.60 |

Against v3, the version on the public listening page, the VHF fading scores are up by 0.13 to 0.29.

## Longer interleaving: two YSF frames (200 ms)

On 2 m at 30 to 60 km/h, about 40% of lost frames came in runs of exactly five: one whole YSF frame (100 ms) wiped out by a fade. `modem/interleave.py` spreads each 100 ms codeword over two consecutive YSF frames. Even payload positions of YSF frame k carry codeword k, and odd positions carry codeword k−1. A fade over one YSF frame now costs two codewords half their bits each, and the convolutional code (rate 0.39) can often rebuild both. The cost is 100 ms more delay, plus one extra voice frame at the end of each transmission.

`tools/interleave_race.py`: 146 MHz, 5 voices × 3 fading seeds, decoded with v3.5. The same channel realisation is used for both depths. Results are in `docs/results/interleave_2m.json`.

| speed | C/N0 (dB-Hz) | PESQ, depth 1 | PESQ, depth 2 | change | frames lost, depth 1 | frames lost, depth 2 |
|---|---|---|---|---|---|---|
| 5 km/h | 52 | 1.72 | 1.66 | −0.06 | 19.2% | 19.5% |
| 5 km/h | 56 | 2.21 | 2.13 | −0.08 | 8.9% | 9.5% |
| 30 km/h | 52 | 2.02 | 2.19 | +0.16 | 13.5% | 11.3% |
| 30 km/h | 56 | 2.69 | 2.83 | +0.13 | 3.7% | 2.5% |
| 60 km/h | 52 | 2.29 | 2.52 | +0.23 | 9.2% | 6.8% |
| 60 km/h | 56 | 2.91 | 2.94 | +0.04 | 1.7% | 1.0% |
| 100 km/h | 52 | 2.49 | 2.79 | +0.30 | 6.2% | 3.9% |
| 100 km/h | 56 | 3.01 | 3.03 | +0.02 | 1.0% | 0.3% |

Depth 2 cuts lost frames by a quarter to two thirds from 30 km/h up, and gains up to 0.30 PESQ where the channel is weak. At walking pace a 2 m fade lasts longer than 200 ms, so spreading doesn't help. Losses then hit two codewords at once, which costs 0.06 to 0.08. Over all eight conditions the mean goes from 2.42 to 2.51. **Depth 2 is the better default for mobile use.** Longer depths would add another 100 ms each for the walking case, which is the case they can't fix.

**Listening round 9** (Jeff, 6 pairs, both sides through the same fades):

| Pair | Channel | Pick | PESQ (depth 1 / depth 2) |
|---|---|---|---|
| 1 | 30 km/h, fair | tie | 2.62 / 2.74 |
| 2 | 60 km/h, weak | depth 2 | 2.04 / 2.42 |
| 3 | 30 km/h, weak | depth 2 | 2.01 / 1.94 |
| 8 | 100 km/h, weak | depth 1 | 2.39 / 2.48 |
| 10 | 60 km/h, weak, "depth 1 has more distortion" | depth 2 | 1.81 / 1.88 |
| 12 | 5 km/h, weak, "depth 2 drops 'white' less but it sounds like 'wolf'" | depth 1 | 1.90 / 2.00 |

That makes 3 wins for depth 2, 2 for depth 1 and 1 tie. Ears and PESQ disagree on three of the pairs. Depth 2 loses fewer frames, but it changes which words break, and a half-rebuilt word can sound wrong rather than missing. This is a lean towards depth 2, not a clear win. Keep it as an option and test more pairs at 60 to 100 km/h before making it the default.

## What limits the next step: speech data

The shape quantizer is trained on about 2 minutes of speech, nearly all from one male (ve9qrp), and scored on three clips. That is enough to compare structures, but not to train a vector quantizer, which is the obvious next gain (the quantizer step above costs 0.15 to 0.4). Nor is it enough to tune the tracker without fitting the noise. The sandbox can't reach LibriSpeech, VCTK or CMU ARCTIC. (Partly solved later with Speech Commands, see above.)

## Next

1. Done: the public listening page uses v3.5 (rounds 7 and 8).
2. Done: float C port of v3.5 in `c/`, bit-exact with Python on 99.97% of frames (`docs/c-port.md`). Next is fixed point for the C5517, starting with Codec 2's analysis and synthesis.
3. Done: depth-2 interleaving (200 ms): +0.02 to +0.30 PESQ from 30 km/h up (most on weak signals), −0.07 at walking pace. Round 9 by ear: depth 2 won 3, lost 2, tied 1. Test more fast-mobile pairs before making it the default.
4. v3.6: the 9 + 9 + 8 + 8 codebook (29 KB as 8-bit values, a quarter of the search) scores the same as the shipped one by PESQ, and round 9 heard no difference (5 ties out of 5). Switch to it so the PC tools and the DSP share it.
5. Retrain the codebook on VCTK or more LibriSpeech (train-clean-100) when someone can upload it.
6. Still open by ear: the 390 Hz voice (Codec 2 preferred twice, though v3 is closer to that band-limited original).
