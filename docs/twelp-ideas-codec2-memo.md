# A better open 2400 bps vocoder: what we can borrow from TWELP

*Written 2026-10-30. Follows on from `vocoder-comparison-memo.md`. Scoring script: `tools/score_samples.py`.*

## Short answer

- **It's worth doing, but the realistic goal is "open, matches AMBE+2, holds up better under bit errors". Clearly beating AMBE+2 is not a realistic goal.** By DSP Innovations' (DSPINI) own PESQ numbers, Codec 2 2400 sits about 0.4 PESQ below AMBE+2, and TWELP sits about 0.15 to 0.25 above it. Classic, patent-expired techniques (the MELP family) are enough to close most of that 0.4 gap. TWELP's extra margin comes from proprietary tuning that it doesn't publish.
- **TWELP has almost no public technical detail.** There are no patents, no papers, and one sentence on what the algorithm does. Everything in it that we can actually name maps onto well-known public techniques: pitch-synchronous residual modelling, mixed periodic, noise and transient excitation, trained quantizers, and joint source and channel coding with UEP and soft decisions.
- **Nobody is doing this in the open.** Upstream Codec 2 has frozen its classic modes (only 3200 for M17 is maintained) and moved to neural codecs (RADE), which are far too heavy for the C5517. I found no open TWELP-inspired codec. The only fixed-point Codec 2 work I found is a hobby decoder-only port for the RP2040.
- **Compute fits.** I estimate about 50 to 100 MHz of the C5517's 200 MHz for encode, decode, noise suppression and soft-decision FEC. Like everything on the radio, it's gated on WS3 (getting DSP code loaded).

## 1. What TWELP publicly is

All of this comes from the vendor, and I found no independent evaluation.

- **Algorithm:** the only description is "three-component representation of pitch-synchronous LPC residual … quantized by unique speech-driven quantizers in conjunction with LPC-parameters", plus "advanced tri-wave model of excitation" with pitch-synchronous analysis and synthesis ([twelp.pro](https://twelp.pro/), [TWELP 2400](https://dspini.com/vocoders/lowrate/twelp-lowrate/twelp2400)). Nothing public says what the three components are or how voicing is decided.
- **Format:** 8 kHz input, 20 ms frames, 40 ms algorithmic delay. A frame is 48 bits at 2400 bps, or 72 bits at 3600 bps with FEC. That is exactly Codec 2 2400's frame, and exactly the FTM-300D's DN voice slot (3600 bps gross). Rates from 300 to 9600 bps are offered ([CMX7262 page](https://dspini.com/vocoders/lowrate/twelp-lowrate/twelp-cmx7262-vocoder)).
- **FEC:** 3600 bps is "joint source-channel coding" using UEP-RCPC (unequal-error-protection, rate-compatible punctured convolutional codes), with soft decisions recommended. The CMX7262 chip adds a 1 to 4 frame interleaver and 4-bit soft metrics.
- **Claimed quality** (PESQ P.862, ITU-T P.50 speech, 20 languages):

  | Codec | PESQ | Source |
  |---|---|---|
  | AMR-NB 4750 | 3.255 | [TWELP 2400](https://dspini.com/vocoders/lowrate/twelp-lowrate/twelp2400) |
  | TWELP 2400 | 3.226 | same |
  | AMBE+2 (DMR, 3600 with FEC) | 3.030 | [dspini.com](https://dspini.com/) |
  | MELPe 2400 | 2.999 | TWELP 2400 page |
  | TWELP 700 | 2.747 | [Codec2 vs TWELP](https://dspini.com/twelp/codec2-vs-twelp-2400) |
  | Codec 2 2400 (v1.2) | 2.654 | same |

  At 5% BER, they quote TWELP 3600 at 2.650 with hard decisions and 2.998 with soft decisions, against AMBE+2 3600 at 2.711. So **soft-decision decoding is worth about 0.35 on its own**.
- **Compute:** 66 peak MIPS for encode plus decode in generic C (72 with noise suppression and AGC). The figure is 44 MIPS on a TI C64 and 23 MIPS on a Cortex-M4 (the M4 figure doesn't add up against the others, and the C55 figure is listed but left blank). Encoder code is 23 to 69 KB, with about 34 KB of tables.
- **Licensing:** a binary object library licensed from DSPINI only. The CMX7262 chip says it is "licensed solely for use within this microchip" and is protected by "copyrights and trade secrets". The vendor says TWELP is "not a variety or combination of well-known speech coding methods, patented comprehensively". **I found no patent numbers.**

**Our own check of those numbers.** I scored the existing `samples/` (narrowband PESQ and ESTOI, 4 clean clips: hts1a, hts2a, kristoff, ve9qrp). david4 and vk2tpm are noisy recordings: the codec output clips and the scores come out meaningless, so I left them out.

| | C2 1600 | C2 2400 | C2 3200 | Opus 6k | Opus 8k |
|---|---|---|---|---|---|
| PESQ | 2.57 | **2.77** | 2.96 | 2.57 | 3.74 |
| ESTOI | 0.65 | 0.70 | 0.74 | 0.73 | 0.84 |

Our Codec 2 2400 score of 2.77 agrees reasonably well with DSPINI's 2.654 on their larger set, so their ranking looks plausible. One caution: PESQ isn't calibrated for parametric vocoders (here it puts Opus 6k level with Codec 2 1600, which doesn't match how they sound). Use it to compare versions of one codec, not to declare a winner.

## 2. Where Codec 2 2400 loses, and which ideas fix it

Codec 2 2400 is a sinusoidal coder. It sends pitch, energy, one voiced/unvoiced bit per 10 ms, and scalar-quantized LSPs, and it synthesizes phase from the LPC envelope ("phase0"). Its known weaknesses are a buzzy or reverberant sound from the all-or-nothing voicing and the synthetic phase, and inefficient spectral quantization. Here is how the ideas map, with the cheapest and most certain first:

| # | Idea | Where it comes from | Bits | Expected gain | Patent status |
|---|---|---|---|---|---|
| 1 | **UEP FEC with soft decisions** in the 1200 bps of DN FEC: RCPC or a short polar/LDPC code, protection ranked by each bit's sensitivity, soft metrics taken from the C4FM demodulator | TWELP 3600, FreeDV practice | 0 source bits | Large on real channels (vendor's own figure: about +0.35 at 5% BER). Nothing on a clean channel | Convolutional codes, RCPC and UEP are 1980s techniques and expired |
| 2 | **Multi-stage predictive VQ of the LSFs** in place of scalar LSPs, plus joint coding across the two 10 ms subframes | MELPe, Codec 2's own newamp1 | Frees about 10 to 15 bits per frame | Same or better envelope with fewer bits. This pays for 3 and 4 | Expired (1990s). newamp1 is LGPL |
| 3 | **Mixed excitation:** 4 to 5 band voicing strengths, or a voicing cutoff frequency, instead of 1 bit | MELP, MBE, "tri-wave" periodic plus noise | About 4 to 8 | The biggest single quality fix: removes buzziness, the largest part of MELPe's lead over Codec 2 | MELP and MBE core patents date from the mid-1990s and should have expired (still verify) |
| 4 | **Pitch-synchronous pulse shape:** a small codebook (about 4 to 6 bits) for the glottal pulse or phase-dispersion shape, and a jitter/aperiodic flag for onsets and creaky voice. This is our guess at TWELP's "third wave" | MELP pulse dispersion and jitter, waveform-interpolation SEW/REW | About 4 to 7 | Less "synthetic" phase, cleaner onsets | Expired (MELP, early WI work). Avoid copying any later WI patents literally |
| 5 | **Trained ("speech-driven") quantizers** for pitch and energy, with interframe prediction | Generic VQ practice | Saves a few bits | Small | Free |
| 6 | **Front-end noise suppression and AGC** (fixed-point Speex preprocess or a simple spectral subtraction) | TWELP NCSE claim | 0 | Large in a car with road noise. Nothing on clean speech | Speex is BSD |
| 7 | **Retuned adaptive postfilter** | Codec 2 already has one (beta/gamma) | 0 | Small, but nearly free to try | Free |

**Do not borrow** anything from AMBE+2 itself (DVSI's later patents on tone handling, interoperability and transcoding may still be in force), and do not disassemble a TWELP library or the CMX7262. Everything above comes from public, old literature. This is not a formal freedom-to-operate search. For personal amateur use the risk is low. Before shipping it in a product, have a patent attorney check items 3 and 4.

**Realistic target:** codec 2 2400 at about 2.8 PESQ moves to about **3.0 to 3.1 at the same 48 bits** with items 2 to 5 (MELPe's own level is 3.0), and holds up better than AMBE+2 under bit errors with item 1. Reaching TWELP's 3.2 would take long, data-driven tuning of every quantizer, and there's no guarantee it's reachable.

## 3. Cost on the C5517

| Block | Estimate | Note |
|---|---|---|
| Codec 2 2400 core, fixed point | 40 to 80 MHz | From the earlier memo. The FFTs go on the FFT accelerator |
| MSVQ search (2 to 4 stages, M-best) | about 3 to 8 MHz | Dual-MAC friendly |
| Mixed excitation synthesis and pulse codebook | about 2 to 5 MHz | Bandpass shaping of a pulse train plus noise |
| Noise suppression and AGC | about 5 to 10 MHz | Shares the analysis FFT |
| Soft Viterbi K=7 at about 3.6 kbps | about 2 to 5 MHz | The C55x has Viterbi-friendly instructions |
| **Total** | **about 50 to 100 MHz** | Same range as TWELP's quoted 66 to 72 MIPS |

RAM is about 20 to 40 KB plus 10 to 40 KB of VQ tables, which fits easily in 320 KB. The open question, as before, is how much the C4FM modem itself uses.

The fixed-point port is real work. talkberry's fixed-point Codec 2 decoder on the RP2040 runs about 7.5x faster than the float build ([github.com/hrvach/talkberry](https://github.com/hrvach/talkberry), LGPL, 1300 mode, decoder only), which confirms that fixed point is the way to go and gives some code to start from.

## 4. Is someone already doing this?

- **Upstream Codec 2:** the [README](https://github.com/drowe67/codec2) (2023 refactor) says classic Codec 2 modes are not being developed, except 3200 for M17, and that experimental work belongs in forks. David Rowe's effort has moved to neural speech: **RADE**, including [RADE for land mobile radio over baseband FM](https://arxiv.org/pdf/2509.17286) (2025). That needs about 32 MMACs each way plus a roughly 300 MMACS FARGAN vocoder and about 1 MB of weights, so it can't run on the C5517. It is a strong candidate for the **Pi plus DATA jack fallback** if the DATA jack's 9600 port passes flat (discriminator) audio. That's worth checking.
- **M17 / OpenRTX:** they use stock Codec 2 3200 on Cortex-M4F radios that have a floating-point unit. That's an integration project, not codec improvement (from my general knowledge; I didn't confirm it from their docs this time).
- **talkberry:** fixed-point Codec 2 1300 decoder for the RP2040. A small hobby project (4 commits), no encoder.
- **TWELP-inspired open codecs:** none found.
- **Academic work** (VoCodec and other neural codecs at 0.5 to 3 kbps): GPU-class neural networks, not relevant here.

So **nobody is doing this in the open**: no classical, open codec beyond Codec 2 at 2400 bps for fixed-point DSPs. It would have to live in our own fork.

## 5. Recommendation and plan

1. **Measurement harness (started).** `tools/score_samples.py` gives PESQ and ESTOI on `samples/`. Add P.50 and LibriSpeech-style clips, plus a bit-error channel simulator.
2. **Float prototype on a PC, in a Codec 2 fork (LGPL)**, keeping the 48 bit / 20 ms frame. In order: item 7 (postfilter, free), then 2 (MSVQ), 3 (mixed excitation), 4 (pulse shape). Gate: **PESQ ≥ 3.0 on clean clips, and better by ear.**
3. **UEP plus soft-decision FEC for the DN slot** (72 bits per 20 ms), tested against a simulated C4FM channel. Gate: better than stock Codec 2 2400 with 1200 bps of FEC at 1 to 5% BER.
4. **Fixed-point port** checked against the float build (reusing talkberry's approach), then cycle-counted in TI's C55x simulator or on a C5517 eval board.
5. **On the radio** only once WS3 can load DSP code.

Meanwhile, the on-air comparison still goes through the fallback path (analog FM plus a Pi). RADE-BBFM is worth adding to that list.

Steps 2 and 3 are about 2 to 4 weeks of focused DSP work for a prototype, and the fixed-point port is another month or more. Fall back to stock Codec 2 2400 plus item 1 alone if step 2 misses its gate: that is the cheapest robust win.

## Sources

- TWELP: <https://twelp.pro/>, <https://dspini.com/>, <https://dspini.com/vocoders/lowrate/twelp-lowrate/twelp2400>, <https://dspini.com/vocoders/lowrate/twelp-lowrate/twelp-cmx7262-vocoder>, <https://dspini.com/twelp/codec2-vs-twelp-2400>, CMX7262 datasheet <https://www.mouser.com/datasheet/2/976/CMX7262_FI1_ds-1569896.pdf>
- Codec 2 status: <https://github.com/drowe67/codec2> (README)
- RADE LMR/BBFM: <https://arxiv.org/pdf/2509.17286>. Code at <https://github.com/drowe67/radae>
- talkberry: <https://github.com/hrvach/talkberry>
- VoCodec: <https://arxiv.org/html/2606.05892>
