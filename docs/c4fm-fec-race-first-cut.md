# C4FM burst channel and a first-cut FEC race

*Written 2026-10-30. Answers `melp-patents-and-c4fm-lmr60-notes.md`. Code: `c4fm_sim.py`, `fec_race.py` and `validate.py` in this folder. Raw numbers: `results_first_cut.json`. Everything here is simulation, written from scratch in Python, with no external modem or codec code.*

## Short answer

- **lmr60's 200 µs two-path cannot be used for C4FM as it stands.** With a discriminator receiver, the symbol error rate is about 46% at 25 dB, so no code at this rate survives it. Your ISI concern was right, and it's worse than an error floor: whenever the delayed path is the stronger one, the receiver reads the neighbouring symbol. C4FM holds up to about **10 µs** of delay spread, degrades at 25 µs, and fails from 50 µs. So the FEC race uses **flat Rayleigh**, with delay spread swept as a separate stress test.
- **On flat Rayleigh, soft-Viterbi convolutional coding with an 80 ms interleaver (`conv4`) wins clearly.** Interleaved RS over GF(256) with an erasure gate **loses at every operating point**. Even with perfect knowledge of which bytes are bad (an oracle, not achievable), RS only matches `conv4` at UHF and loses on 2 m.
- **Your 2 m prediction holds.** At 146 MHz and 30 km/h, the 80 ms interleaver gives nothing over no interleaving, because fades outlast it. At UHF the same interleaver cuts bad frames by 3 to 8 times.
- **Repeating the most sensitive 24 bits in the next frame** (soft-combined) protects them about as well as `conv4`, with only 20 ms of latency. But it leaves the other 24 bits uncoded. That points to the real next candidate: **UEP convolutional coding** (stronger code on class A, lighter on class B), rather than RS.
- **Two corrections to the superframe plan:** a block superframe isn't causal as drawn, so the latency is about twice the superframe length. And Fusion's 100 ms frame suggests 5-frame superframes, not 4 or 8. Details in §4.
- **Patents:** six of your seven numbers check out. One date nit is in §5.

## 1. The simulator and its checks

**Chain:** dibits, then P25/YSF Gray map to ±1/±3, then a raised-cosine (α 0.2) frequency pulse at 600 Hz per level, then FM. Then the channel: flat Rayleigh, or two paths with independent fading at equal mean power and delay τ, with a Jakes-spectrum sum-of-sinusoids generator at fd = v·f/c, plus AWGN. On receive: a ±6 kHz IF filter (the FTM-300 selectivity spec says −6 dB at 12 kHz), a discriminator, a 3 kHz post-detection lowpass, symbol-centre sampling, and max-log bit LLRs computed with a noise variance estimated over a 24-symbol window. That window lets the metrics shrink honestly in a fade.

**Checks:**

| Check | Simulated | Theory or spec |
|---|---|---|
| Fading level-crossing rate at −10 dB, 146 MHz / 60 km/h | 5.82 /s | 5.81 /s |
| Average fade duration below −10 dB, 146 MHz / 60 km/h | 16.4 ms | 16.4 ms |
| Level-crossing rate / fade duration, 446 MHz / 60 km/h | 18.3 /s, 5.2 ms | 17.9 /s, 5.3 ms |
| Time below −10 dB (flat Rayleigh) | 8.7–10% | 9.5% |
| AWGN channel BER of 1% | Eb/N0 ≈ 10.7 dB | Radio spec 0.19 µV for 1% BER means Eb/N0 ≈ 8.8 dB at a 4 dB noise figure (≈ 10.8 dB at 2 dB NF) |

Your fade-duration and level-crossing figures match these. The receiver is a plain discriminator with a slicer and perfect timing and frequency, so it's about 0 to 2 dB worse than the radio. Its absolute Eb/N0 values are approximate. The comparisons between schemes are what count.

**Not modelled:** sync loss, timing recovery, AFC, AGC and limiter dynamics, impulsive (ignition) noise, and Yaesu's real placement of voice bits inside the frame. I spread the 36 voice dibits evenly across each 20 ms.

## 2. Delay spread: where C4FM stops working

446 MHz, 60 km/h, two equal-power paths, Eb/N0 25 dB:

| τ | Symbol error rate | Bad frames, `conv4` | Bad frames, uncoded |
|---|---:|---:|---:|
| flat (0) | 0.7% | 0.1% | 5.2% |
| 5 µs | 0.7% | 0.07% | 5.8% |
| 10 µs | 0.95% | 0.07% | 7.2% |
| 25 µs | 3.0% | 0.8% | 18% |
| 50 µs | 11% | 13% | 50% |
| 100 µs | 30% | 80% | 81% |
| 200 µs (lmr60) | 46% | 97% | 90% |

Typical rms delay spread for VHF/UHF mobile is about 0.2 to 3 µs, with tens of µs in mountains or simulcast. So for C4FM, lmr60's 200 µs is a simulcast-style failure case, not a hard mobile case. (P25 brought in CQPSK/LSM for simulcast for this reason.) It is the right channel for RADE-BBFM, whose OFDM-like design tolerates it, and the wrong one for testing FEC for a C4FM vocoder. One caveat: my receiver keeps its timing on path 1. A real timing loop would track the stronger path some of the time, so the failure point might move up a little, perhaps to 25–50 µs. It won't reach 200 µs.

## 3. FEC race on flat Rayleigh

The input is always a 48-bit vocoder frame every 20 ms (class A = the first 24 bits), sent in a 72-bit voice slot. 3000 frames (60 s) per condition. A frame counts as **bad** if any class-A bit is wrong. For RS, it also counts as bad if its class-A codeword failed, which is detected.

Schemes:
- **conv1 / conv4:** K=7 (133,171) code at rate 1/2, punctured to 2/3, running continuously, decoded with soft Viterbi. conv1 interleaves within one frame only; conv4 adds a 4-frame (80 ms) interleaver.
- **rs8g / rs8:** 6 × RS(12,8) over GF(256) in an 8-frame superframe, built as in your notes. rs8g uses errors-and-erasures decoding with the noise-variance gate, its threshold tuned for each condition. rs8 uses no gate.
- **rs4g:** the same idea with 6 × RS(6,4) over 4 frames, with the gate.
- **rs8 perfect:** an oracle that is told exactly which bytes are wrong. This is the best any gate could do.
- **rep:** the class-A bits are sent in frame n and again in frame n+1, then soft-combined. Class B is uncoded.
- **unc:** class A with no protection.

**Bad-frame rate (class A), Eb/N0 20 dB:**

| Band, speed | conv1 | **conv4** | rs8g | rs4g | rs8 perfect | rep | unc |
|---|---:|---:|---:|---:|---:|---:|---:|
| 146 MHz, 30 km/h | 3.8% | **1.9%** | 13% | 12% | 5.6% | 2.0% | 8.6% |
| 146 MHz, 60 km/h | 4.0% | **0.9%** | 8.8% | 10% | 2.4% | 0.7% | 8.5% |
| 146 MHz, 120 km/h | 4.3% | **0.5%** | 4.0% | 7.6% | – | 1.2% | 9.6% |
| 446 MHz, 30 km/h | 4.2% | **0.5%** | 8.0% | 11% | 1.9% | 0.9% | 9.3% |
| 446 MHz, 60 km/h | 5.1% | **0.7%** | 6.7% | 9.9% | 0.3% | 1.2% | 12% |
| 446 MHz, 120 km/h | 5.0% | **1.3%** | 11% | 14% | 0.3% | 3.9% | 17% |

**Eb/N0 15 dB** (weak-signal edge):

| Band, speed | conv1 | **conv4** | rs8g | rep | unc |
|---|---:|---:|---:|---:|---:|
| 146 MHz, 30 km/h | 13% | 14% | 41% | **12%** | 25% |
| 146 MHz, 60 km/h | 12% | 8.0% | 38% | **6.9%** | 24% |
| 446 MHz, 60 km/h | 15% | 7.5% | 43% | **7.5%** | 28% |
| 446 MHz, 120 km/h | 17% | **9.1%** | 63% | 12% | 34% |

At 25 dB every coded scheme except rs4g (up to 3.1%) is under 2%, and conv4 is at or below 0.3% everywhere.

**Class-B residual BER at 20 dB:** about 0.1–0.75% for conv4, about 1.0–1.2% for rep (uncoded). At 15 dB: 2.1–5.6% for conv4 and 3.1–3.7% for rep.

**Why RS loses here:**
1. A 2–15 ms Rayleigh fade lands on several bytes in the same frame, and also produces scattered dibit errors around its edges. Byte symbols make every one of those scattered errors cost a whole symbol. Soft Viterbi uses the partial reliabilities instead.
2. The gate isn't sharp. At its best threshold it erases 0.5–16% of bytes and typically catches only 50–85% of the bad ones. Using the true fading gain (as an RSSI-style indicator) helps a little: at 20 dB, 4–14% bad frames vs 7–13%. But even perfect erasure information only matches conv4 at UHF and loses on 2 m.
3. RS(12,8) gets its strength from whole-frame bursts. With flat Rayleigh at these speeds, fades are shorter than a frame at UHF and errors are spread unevenly within frames on 2 m.

RS could still win where losses really are whole frames: sync loss, or pile-ups at repeater handoff. Those aren't modelled. RS also has one real advantage: **its failures are detected**, while a convolutional bad frame is silent and gets interpolated into the neighbouring frames (your poisoning point). The fix is a short CRC on class A (4–6 bits), or the Viterbi path-metric margin as a reliability flag, which costs no bits. That should be part of the next round.

**Interleaving and band:** conv4 vs conv1 at 20 dB improves bad frames by 2 times at 146 MHz / 30 km/h, but 4–9 times at 446 MHz and at 120 km/h on 2 m. At 15 dB on 2 m at 30 km/h it makes no difference at all (14% vs 13%). That's your coherence-time argument, now measured. On 2 m, slow-moving stations need either a longer interleaver (which costs latency) or concealment that can handle 2–3 lost frames in a row.

**Gilbert–Elliott fits** for each condition are in the JSON under `raw`, with bursts defined as errors separated by fewer than 8 clean symbols. Representative values per symbol: 446 MHz / 60 km/h / 20 dB has p(G→B) 0.0047, p(B→G) 0.14, error rate 0 in good and 0.60 in bad. 146 MHz / 30 km/h / 20 dB has 0.0041, 0.11, 0 and 0.55. The p90 burst length is 2–7 ms. A two-state model is too coarse for the 2 m case, where long fades are made of many short bursts. Use the waveform traces for anything to do with sizing interleavers.

## 4. Review of the superframe plan

1. **Causality and latency.** In an RS(12,8) codeword whose 4 parity bytes ride in the same 8 frames as its data, the parity depends on all 8 data bytes. So frame 1 can't be sent until frame 8's speech exists. The encoder has to hold back one superframe and the decoder has to wait for one, so the added one-way delay is about **2 × superframe minus one frame**: about 300 ms for 8 frames and about 140 ms for 4. A block bit interleaver (conv4 here) has the same problem, at about 140 ms for 4 frames. The fix for both is a **diagonal (convolutional) layout**, where each codeword's parity, or each interleaver row, is sent in the frames *after* its data, as CD's CIRC does. The encoder then adds no delay and the decoder delay equals the span (80 or 160 ms). The latency cap in your race should count this end to end.
2. **Frame alignment.** As I understand it, Yaesu System Fusion uses 100 ms frames (960 channel bits, 5 voice sub-blocks in DN). If we keep Yaesu's framing so repeaters still recognise the signal, a 5-voice-frame (100 ms) superframe fits naturally. The byte arithmetic works for 3 × RS(15,10) (30 data + 15 parity bytes = 5 × 9), which survives one lost frame per superframe. I haven't checked the exact DN sub-block layout.
3. **The symbol-wise and GF(4) argument** still points towards a non-binary code matched to dibits, but GF(256) over byte-aligned layouts throws that advantage away. If a non-binary candidate stays in the race, it should be GF(4) or GF(16) aligned to dibits (LDPC, or RS over GF(16) with nibble = 2 dibits). On the C5517 that is a stretch candidate, as you said.

## 5. Patent spot-check (Google Patents and Justia)

Confirmed: **US 5,699,477** (TI/McCree, filed 1994-11-09, expired 2014-12-16). **US 6,122,608** (TI/McCree, switched-predictive LSF quantization, priority 1997-08-28, expired 2018-08-15). **US 5,966,689** (TI/McCree, "Adaptive filter and filtering method for low bit rate coding", priority 1996-06-19, expired). **US 7,139,700** (TI, Stachurski & McCree, "Hybrid speech coding and system", filed 2000-09-22, issued 2006-11-21; Justia shows no expiry date, so the 2024 figure is unverified). **US 6,912,495** (DVSI, filed 2001-11-20, "expires 2023-11-28", which is consistent with a 738-day extension). **US 5,701,390** (DVSI MBE synthesis, expired 2015-02-22). Also confirmed: US 6,463,406's specification really does describe the five-band pulse/noise mixture, the jitter generator and the pulse dispersion filter.

**Nit:** US 6,463,406 itself was **filed 1996-05-20** as a continuation of the 1994 application. Because it was filed after 1995-06-08, the "greater of 17 years from issue or 20 years from filing" rule doesn't apply. Its term is 20 years from the earliest parent, about **2014-03-25**, not 2019. It's expired either way.

## 6. Open MELPe code (your follow-up)

- **Rhizomatica/melpe** (labelled GPL-3.0) contains the **STANAG 4591 reference fixed-point code**. The headers read "Copyright (c) 1995–1998 Texas Instruments … All rights reserved" and "Microsoft SC1200 … Fixed Point Implementation Version 7.0 … Copyright (C) 2000". It includes the AT&T noise pre-processor (Rainer Martin, 1999), a TI notice that it "has intellectual property rights on the MELP algorithm", and an ETSI GSM 06.06 basic-op license granted to the US DoD. The GPL label probably can't relicense that. Use it **as a reference only**, for cycle and RAM estimates of a real fixed-point MELPe and as an A/B baseline. Don't copy it into our fork.
- **melpe-rs 0.1.2** (MIT, HeroesLament, 2026) is clean float Rust that runs without the standard library. It is *not* STANAG-conformant: scalar LSFs, 41 bits per 67.5 ms, no MSVQ, no Fourier magnitudes, no test vectors. It is fine to borrow from for 5-band mixed excitation and jitter.

## 7. Next round (proposed)

1. **UEP convolutional coding with the class-A CRC or path-metric flag**, against conv4 and rep, at the same 48→72 rate. For example: class A at rate 1/2 plus a 4-bit CRC, class B at about 0.8.
2. **A diagonal interleaver** at 80 and 160 ms, scored on bad-frame **runs** (how many consecutive frames concealment has to cover), above all at 2 m and 30 km/h.
3. **Score PESQ against Eb/N0** once a codec with a bit-sensitivity ranking exists. Until then, class-A bad frames and class-B BER stand in for it.
4. **Add impulsive (ignition) noise and a timing-recovery loop** to the simulator before trusting results below 15 dB.
5. **Drop RS over GF(256)** unless sync-loss or whole-frame erasure traces turn up that change the picture.
