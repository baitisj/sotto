# Follow-up research on improving Codec 2 at 2400 bps

*Written 2026-10-30. Answers Jeff's notes `codec2-2400-improvement-notes.md` on `twelp-ideas-codec2-memo.md`. Sources are the Codec 2 source tree and its design document (`doc/codec2.tex`, read locally from a clone of github.com/drowe67/codec2), plus web sources linked inline.*

## Short answer

- **Your notes hold up against the source code.** The 2400 bit table is right (36 LSP / 8 Wo+E / 2 voicing / 2 spare), and Option A (stay sinusoidal) is a much smaller change than either of us assumed. Codec 2's voicing estimator is already the MBE per-harmonic test, and its decoder already chooses voiced or random phase one harmonic at a time. Band voicing is mostly a matter of changing a loop bound.
- **Two of the planned building blocks already exist in the tree.** A 27-bit memoryless multi-stage LSP VQ (`lspjmv`, used by the 1200 mode) can be tested against the 36-bit scalar quantizer straight away. And `c2sim` can dump and reload the full per-frame model (`--modelout` / `--modelin`), which is exactly the oracle harness you proposed. We only need to write the Python side.
- **The cheapest oracle ceiling is free:** `c2sim` run without `--phase0` keeps the original phases. Comparing it against `--phase0` measures how much quality the phase model is losing before any voicing or excitation work starts.
- **The usable saving is 9 bits, not 11.** That's 27 bits with lspjmv vs 25 in MELPe, unless we train our own LSP VQ. The 48-bit budget below still closes, but with nothing spare.
- **Still open:** I couldn't find MELP patent numbers (Google Patents refused automated access), published C4FM burst-error statistics, or whether the DATA jack's 9600 output is flat. That last one is a quick check in your owner's manual or on the bench.

## 1. What the Codec 2 source confirms

**Bit allocation (`src/codec2.c`, `codec2_encode_2400`).** The table in your notes is exact. One detail matters for the plan: pitch, energy and the LSPs are sent **once per 20 ms**, and the first 10 ms frame is interpolated, so only voicing is sent at a 10 ms rate. So the "joint coding across subframes" idea in my first memo was moot, and the frame is already close to MELPe's 22.5 ms.

**Voicing is already MBE-style (`src/sine.c`, `est_voicing_mbe`).** For each harmonic up to 1 kHz, it fits an ideal windowed sinusoid, adds up the fit error, and compares the overall SNR to a threshold, which yields one bit. Giving per-band voicing strengths means computing that same SNR per band across 0 to 4 kHz instead of once over 0 to 1 kHz. The design document says it is "a variation of the MBE voicing algorithm [Griffin 1988]".

**Synthesis is already per harmonic (`src/phase.c`, `phase_synth_zero_order`).** Voiced harmonics get the coherent excitation phase `ex_phase*m`, and unvoiced ones get a random phase. Replacing the single `model->voiced` flag with a per-harmonic or per-band flag is the whole of the decoder change for Option A. Graded strengths (partially voiced bands) would need a small phase-jitter or noise-mixing rule on top.

**The author's own reasoning (`doc/codec2.tex`, §phase/postfilter):**
- The document says "(5-12) bits/frame are required to transmit the frequency selective voicing information", so Codec 2 deliberately used a **zero-bit decoder trick** instead. That's the "postfilter", which randomizes the phase of harmonics below an estimated background-noise level. In other words, Codec 2's "postfilter" is a substitute for mixed voicing, **not** a formant postfilter. The formant-style one is the separate LPC postfilter (`--lpcpf`, beta/gamma). My first memo's item 7 meant the LPC postfilter.
- Known defects the document lists, which are now candidates for experiments:
  1. With phase0, voicing errors sound clicky or staticky.
  2. Quality drops further when H(z) comes from quantized amplitudes.
  3. **Phase tracks are not kept continuous after filtering by H(z)**, which causes discontinuities when the envelope changes fast.
  4. Phase0 sounds close to the original phases through a small loudspeaker, but worse on headphones.

  Item 3 is a cheap, zero-bit decoder fix to try alongside the oracle work.
- The author also notes: "Conventional wisdom (AMBE, MELP) says mixed voicing is required for high quality speech." He never tested that in Codec 2. That is exactly your oracle experiment 1.

**The 27-bit LSP MSVQ already exists (`src/quantise.c`, `lspjmv_quantise`).** It has three 9-bit stages: a 10-dimensional first stage, then a split second stage on the even and odd LSP residuals, searched with weights. It's **memoryless** (no interframe prediction), so an error in one frame doesn't propagate into the next. Codec 2 1200 uses it, and `c2sim --lspjmv` exposes it. It isn't an M-best search, so the stage-1 choice is greedy, and 2 to 4 survivors might lower distortion for very little compute. I don't know what data it was trained on.

**Oracle tooling exists (`src/c2sim.c`).** `--modelout file` writes the `MODEL` struct (Wo, L, A[1..L], phi[1..L], voiced) every 10 ms, and `--modelin file` synthesizes from an edited file. Run with no quantization flags, c2sim is the unquantized model. Each quantization step can be switched on separately (`--lpc 10 --lsp | --lspjmv`, `--phase0`, `--dec 2`, `--postfilter`, `--lpcpf`, `--rateK`, `--hand_voicing`). So the oracle loop is: c2sim analysis, then Python edits to the model (oracle band voicing, amplitude corrections), then c2sim synthesis, then the scorer. Only Option A's band-voicing synthesis needs a C change, about 20 lines in `phase.c`.

**Rate K (newamp1) is Codec 2's amplitude-domain machinery.** It resamples the harmonic amplitudes to K=20 mel-spaced points in dB, removes the mean, applies a microphone equalizer, and uses a 2-stage 9+9-bit M-best VQ (700C). The design document itself says "The VQ was trained on just 120 seconds of data - way too short", and that it has trouble with some languages (German, Japanese). David Rowe's 2023 paper "FreeDV-015 Codec 2 Rate K Resampler" (<https://github.com/drowe67/misc/blob/master/ratek_resampler/ratek_resampler.pdf>, not read yet) proposes improvements. There is no rate-K mode near 2400 bps.

## 2. Answers to your five questions

**1. Option A or B? Nothing forces the choice. I agree with A first.** No WS3 or C5517 constraint picks the architecture. The FFT accelerator suits sinusoidal synthesis, which Codec 2 does with FFTs, but LPC-excitation synthesis is cheap too. Option A is now known to be a small change: the encoder already computes per-harmonic voicing, and the decoder already switches phase per harmonic. Option B stays the fallback, used only if band-voicing oracles can't remove the buzz.

**2. Residual domain or harmonic-amplitude domain for the excitation shape? Harmonic-amplitude domain, under A.** On a sinusoidal decoder, MELPe's 10 residual Fourier magnitudes are the same thing as a correction to the harmonic amplitudes on top of the LSP envelope. The natural form here is a small rate-K-style correction vector (a few mel bands, in dB, 8-bit VQ) applied to the A[m] values before synthesis. It hasn't been prototyped in Codec 2 or in this project. The oracle version is easy: feed the true A[m] (unquantized amplitudes) while keeping the LSP-quantized envelope everywhere else, and see how much of the gap closes.

MELP's own evidence that Fourier magnitudes help is weak. I found no published ablation. The only hint is in McCree & De Martin (ICASSP 1998): "Only for clean flat speech was the Federal Standard preferred, probably due to the presence of the Fourier Series magnitudes" (5 listeners, no percentages; <https://imgserverweb.polito.it/web/res/2011/02/melp_icassp1998.pdf>). So the oracle test has to come first, which supports your ordering.

**3. Training corpus.** None of these are telephone-band. We'd downsample to 8 kHz and add augmentation (microphone and IRS-style filtering, car noise), because the Codec 2 document warns that VQs fail on unfamiliar microphone responses.

| Corpus | Size | License | Notes |
|---|---|---|---|
| LibriSpeech | about 1000 h, English, 16 kHz | CC BY 4.0 | Speaker-disjoint train/dev/test splits, good for holding out speakers ([openslr 12](https://www.openslr.org/12/)) |
| Multilingual LibriSpeech | 8 languages including DE, ES, FR | CC BY 4.0 | Covers the language problem newamp1 had ([openslr 94](https://www.openslr.org/94/)) |
| VCTK 0.92 | 110 English speakers, studio | License file not read (believed CC BY 4.0, check) | [datashare.ed.ac.uk](https://datashare.ed.ac.uk/handle/10283/3443) |
| Common Voice | many languages, crowd microphones | Not verified (moved to Mozilla Data Collective in Oct 2025) | Useful precisely because the microphones are messy |
| ITU-T P.501 test signals | test set, not for training | Terms not stated | [itu.int](https://www.itu.int/rec/T-REC-P.501/en) |

**4. Off-air C4FM error patterns? None are available, so the burst model starts synthetic.** I found no published C4FM, DMR or P25 burst statistics or Gilbert-Elliott parameters. The best open model is **lmr60** from the RADE LMR paper. It's the TIA-102.CAAA-E two-path Rayleigh channel (200 µs delay, 60 km/h, maximum Doppler fd ≈ 25 Hz at 450 MHz, i.e. a Doppler spread of about 50 Hz), which the authors say turns impulsive below threshold (<https://arxiv.org/pdf/2509.17286>; code at github.com/drowe67/radae). We'd run C4FM symbols through lmr60 at 4800 symbols/s, plus a Gilbert-Elliott layer for ignition noise.

Real patterns would need a known transmitted payload. One route: an RTL-SDR records your own radio's DN transmissions while mobile, and an open C4FM demodulator measures errors on the frame structure that is already known (sync and FICH with its CRC). It's worth doing later. It isn't needed to start.

**5. Listening panel.** That one is for you. Even 3 or 4 people doing a blind A/B or DCR on a dozen clips would do. I can build the randomized test page.

## 3. Bit budget, corrected for what exists

| Parameter | C2 2400 now | With in-tree lspjmv | With our own 25-bit LSF VQ |
|---|---:|---:|---:|
| LSPs | 36 scalar | 27 (9+9+9) | 25 |
| Wo + energy | 8 | 8 | 8 |
| Voicing | 2 (1 per 10 ms) | 2 overall + 3 band pattern | 2 overall + 4 band + 1 aperiodic |
| Amplitude correction (rate-K style) | 0 | 8 | 8 |
| Spare | 2 | 0 | 0 |
| **Total** | **48** | **48** | **48** |

One more idea borrowed from MELPe: in unvoiced frames, MELP reuses its band-voicing, Fourier-magnitude and aperiodic bits **as 13 FEC parity bits**, because they carry no information there (RFC 8130 / draft-ietf-payload-melpe-02 Table 3.1; arXiv 1406.6473). We can do the same with the voicing-pattern and correction bits. That's free extra protection exactly when the frame is most fragile.

## 4. Patents and licensing (still incomplete)

- Wikipedia: "the original MELP related patents have expired by now". It also says **MELPe** "is subject to IPR licensing from … Texas Instruments (2400 bit/s MELP algorithm / source code), Microsoft (1200 bit/s transcoder), Thales Group (600 bit/s rate), Compandent, and AT&T (Noise Pre-Processor NPP)" (<https://en.wikipedia.org/wiki/Mixed-excitation_linear_prediction>).
- Practical rule: borrow from **1990s MELP (MIL-STD-3005) and MBE (Griffin 1988)** publications. Don't use MELPe's reference code, the AT&T noise pre-processor, or the 1200/600 transcoding schemes. Use Speex-style noise suppression instead.
- US 6,453,287 (Georgia Tech, MELP plosive enhancement, filed 1999) is listed as "Expired – Fee Related" (<https://patents.google.com/patent/US6453287>).
- I couldn't retrieve the TI core MELP patent numbers or dates, because Google Patents refused automated search. Before anything is distributed beyond personal amateur use, someone should do a proper search.

## 5. DATA jack (for RADE-BBFM on the Pi)

Still unresolved. Yaesu's manual site blocks automated fetches, and the service manual's text layer only gives "DATA Jack Impedance: 10 k Ohms" (the schematics are images). On Yaesu's generic 6-pin mini-DIN data port the RX9600 pin bypasses de-emphasis and audio filtering (<https://en.wikipedia.org/wiki/9600_port>).

On this radio, though, receive audio may be demodulated inside the C5517 DSP, so "flat" depends on Yaesu's DSP filtering. Two quick checks settle it:
1. Look up the DATA jack pinout and the 9600 setting in your owner's manual.
2. On the bench, inject a sweep (or a 9600 G3RUH signal) from a second radio and look at the RX9600 pin on a sound card.

## 6. Revised first steps

These follow your §8 order, front-loaded with the experiments the existing tooling makes nearly free:

0. **Get Codec 2 building.** It was blocked in my sandbox. Either allow the build or run `cmake .. && make c2sim c2enc c2dec` on your machine.
1. **Harness v2:** the LSF spectral-distortion and outlier metric, speaker-held-out LibriSpeech and MLS clips at 8 kHz, and a blind A/B page.
2. **Free ceilings (about a day):**
   - original phases vs `--phase0` (the phase-model gap)
   - unquantized model vs `--lpc 10 --lsp` vs `--lspjmv` (the quantization gap; spectral distortion for the 27-bit vs 36-bit question)
   - `--postfilter` on and off on the noisy clips
3. **Oracle experiments via `--modelin`:** band voicing (about 20 lines of C in `phase.c`), true-amplitude correction, and both together. Then decide whether Option A is enough.
4. **Quantizers and the bit table**, then UEP plus soft-decision FEC on lmr60, as in your notes.

## Sources

- Codec 2 source and design document: <https://github.com/drowe67/codec2> (`src/codec2.c`, `src/sine.c`, `src/phase.c`, `src/postfilter.c`, `src/quantise.c`, `src/c2sim.c`, `doc/codec2.tex`)
- MELP 2.4 kb/s bit table: McCree & De Martin, ICASSP 1998 (<https://imgserverweb.polito.it/web/res/2011/02/melp_icassp1998.pdf>); <https://arxiv.org/pdf/1406.6473>; <https://datatracker.ietf.org/doc/html/draft-ietf-payload-melpe-02> (published as RFC 8130)
- MELP/MELPe IPR: <https://en.wikipedia.org/wiki/Mixed-excitation_linear_prediction>; <https://patents.google.com/patent/US6453287>
- Corpora: <https://www.openslr.org/12/>, <https://www.openslr.org/94/>, <https://datashare.ed.ac.uk/handle/10283/3443>, <https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0>, <https://www.itu.int/rec/T-REC-P.501/en>
- lmr60 channel: <https://arxiv.org/pdf/2509.17286>
- 9600 port: <https://en.wikipedia.org/wiki/9600_port>
