---
title: "Glossary"
---

# Glossary

[Course home](README.md)

Terms used in the sotto code, the design notes in `docs/`, and this course, in plain words. Names in `code font` are how the term appears in the code. The chapter where each idea is explained is in brackets.

### A
**A (amplitudes)**: `A` in the model. The loudness of each harmonic in one 10 ms frame. `A[1]` is the first harmonic, `A[L]` the last. [2]

**Analysis**: the encoder's first job: measuring pitch, voicing and harmonic amplitudes from the microphone signal. sotto uses Codec 2's analysis, with its own pitch and voicing tracker on top (v3.5 uses `analyse(x, "tracked3")` in `sim/vocoder_lab.py`; the tracker is in `sim/sinusoid.py`). [2]

**AMBE / AMBE+2**: the closed, licensed vocoder used by Yaesu System Fusion and other digital radios. sotto aims to match its quality with open code.

### B
**Band voicing**: mixed voicing done simply: harmonics below a cutoff frequency are voiced and those above it get random phases. Tested for v1 with no PESQ gain, then brought back in v3.2 after listeners heard "five-anuh". sotto's cutoff is 1,000 Hz (`MIX_HZ`, `mixed_cutoff()`). See mixed voicing. [2, 5]

**Bit**: a single 0 or 1. With n bits you can send one of 2ⁿ messages. [1, 4]

**Bit allocation**: deciding how many bits each number in a frame gets. sotto's old scalar shape quantizer used **greedy bit allocation**: it handed out bits one at a time, each to whichever number it helped most. [4]

**Blind A/B test**: a listening test where the listener hears two versions of a clip, labeled only A and B, and says which is better or that they're the same. They don't know which codec is which. See listening round. [7]

**Bit rate**: bits per second. sotto's vocoder runs at 2,400 bits per second; the radio carries 9,600. [1, 6]

### C
**CC BY**: a Creative Commons license that lets anyone reuse a work if they credit the authors. sotto's codebook is trained only on CC BY speech, so it can be shipped. [4, 7]

**C4FM**: "4-level FM". The radio signal sotto sends: the frequency hops between four values (±600 and ±1,800 Hz) 4,800 times a second, carrying 2 bits per hop. [6]

**C5517**: the TI digital signal processor (DSP) chip inside the Yaesu FTM-300D radio, where sotto is meant to run one day.

**c2sim, c2enc, c2dec**: Codec 2's command-line programs. `c2sim` runs the analysis and synthesis separately, so experiments can edit the model in between (`--modelout`, `--modelin`). `c2enc` and `c2dec` are the full Codec 2 encoder and decoder. [7]

**Codebook**: the list of allowed patterns in a vector quantizer. The encoder sends the *number* of the closest entry instead of the pattern itself. sotto's three codebooks have 4,096, 2,048 and 2,048 entries of 19 numbers each. [4]

**CODEC_DELAY**: the fixed 160-sample (20 ms) delay used to line up every decoded clip with the original before scoring (`sim/audio_race.py`). It replaced a waveform-matching search that picked wrong delays for vocoders with made-up phases. [7]

**Codec**: short for coder-decoder. Any system that packs data into bits and unpacks it again. A vocoder is a codec for voice.

**Codec 2**: an older open-source vocoder by David Rowe. sotto borrows its analysis (including its pitch and voicing estimates, which sotto's tracker starts from) and its synthesizer, and keeps a copy of its source code in `codec/codec2/` (under its own LGPL license). [1]

**Concealment**: hiding a lost frame from the listener. Since v3.4 it's done in sotto's decoder: hold the last good frame for 40 ms, fade it by 6 dB every 20 ms, and go silent after 80 ms (`SottoV34.decode()`; the v3.5 settings are `hold=2`, `slope=6`, `max_lost=4`). Codec 2 instead repeats the last good frame up to 3 times at full level, then mutes. [6]

**Convolutional code**: an error-correcting code in which every output bit mixes the last several input bits (7 for sotto: "K = 7"). Decoded with the Viterbi algorithm. [6]

**CRC (CRC-8, CRC-16)**: "cyclic redundancy check". A short fingerprint (8 or 16 bits) computed from a block of data, which lets the receiver tell whether the block arrived intact. It detects errors but doesn't fix them. [6]

### D
**dB (decibel)**: a scale for loudness or power that works by ratios. +10 dB is 10 times the power; +6 dB is about 4 times; +3 dB is about 2 times. [3, 4]

**dB-Hz (C/N₀)**: how strong a radio signal is compared with the noise, measured per hertz of bandwidth. In the test conditions, 52 dB-Hz is a weak signal and 56 dB-Hz a somewhat better one. [6]

**DCT (discrete cosine transform)**: rewriting a list of numbers as the sizes of cosine waves added together. sotto applies it to the 20-point envelope shape, so most of the shape ends up in the first few numbers. JPEG uses the same idea. `DCT` in the code is the 20 × 20 table. [3]

**Decimate / interpolate**: decimating means keeping only every second frame (sotto sends one analysis per 20 ms out of two). Interpolating means filling the missing frames in with values halfway between their neighbors. `decimate_interp()`, `interp_wo()`. [4]

**Decoder**: the receiving half of a codec. sotto's decoder turns 48 bits into 20 ms of sound. `SottoV35.decode()` (most steps are inherited from `SottoV0.decode()`). [5]

**Discriminator**: the part of an FM receiver that turns frequency back into a voltage. The softmodem reads its output. [6]

**DN / VW**: two voice layouts in System Fusion. DN ("digital narrow", also called V/D mode 2) uses part of each frame's payload for voice; VW ("voice wide", also called voice full-rate) uses all 720 payload bits. sotto uses the VW slot, protecting its voice much more strongly. [6]

**Doppler (fd)**: how fast the fading changes, which depends on the radio frequency and how fast you're moving. 446 MHz at 60 km/h gives about 25 Hz; 146 MHz at 30 km/h about 4 Hz. [6]

### E
**Encoder**: the sending half of a codec. `SottoV35.encode()`. [1]

**EARS**: a collection of studio speech recordings. sotto uses it only for testing, because its license doesn't allow shipping a codebook trained on it. [7]

**Edge (voicing)**: one of the four voicing codes: one 10 ms half of the frame is unvoiced and the other mixed. Whether it's a start (U then M) or an end (M then U) is worked out from the frame before. [2, 4]

**Encoder race**: an experiment where encoders (Codec 2 2400 and the sotto versions) send through the identical radio chain with the same fading, averaged over three fading patterns, and are scored the same way. `sim/encoder_race.py`, results in `docs/results/encoder_race.json`. [6, 7]

**Energy**: how loud a frame is: the sum of the harmonics' powers, in dB. Sent with 5 bits from 10 to 80 dB. Since v3, code 0 means true silence (see silence). [4]

**Envelope (spectral envelope)**: the smooth outline across the tops of the harmonics. It describes the shape of the throat and mouth, and carries most of the words. [3]

**Erasure**: a bit or frame the receiver knows is missing or unreliable, as opposed to one that is silently wrong. [6]

**ESTOI**: a computer score that predicts intelligibility (how many words a listener would get), from 0 to 1. [7]

### F
**FEC (forward error correction)**: extra bits added before sending so the receiver can fix errors itself, without asking for a resend. sotto's FEC is a convolutional code. [6]

**FICH**: "frame information channel". The 200-bit header in every System Fusion frame that says what kind of frame it is. sotto marks its frames with one spare bit in the FICH (a provisional choice). [6]

**Flywheel**: the receiver's habit of expecting the next frame exactly 100 ms after the last, so it keeps its place through a fade. [6]

**Formant**: a loud bump in the envelope, caused by a resonance of the throat and mouth. Different vowels have formants in different places. [3]

**Formant postfilter**: sotto's decoder step that stretches the envelope's peaks and valleys by 1.35 (in dB) to undo blurring from quantization (1.5 before v3.5). `postfilter_rk()`. Not the same as Codec 2's postfilter. [5]

**Frame**: a chunk of data handled as one unit. A sotto vocoder frame is 20 ms and 48 bits. A System Fusion radio frame is 100 ms and 960 bits, carrying 5 vocoder frames. The analysis also works in 10 ms frames, sometimes called subframes. [1, 6]

**Frequency**: how many times per second something repeats, in hertz (Hz). [2]

### G
**Glorp**: listeners' word for the gargle heard when the woman's pitch went above Codec 2's 400 Hz limit. It led to sotto's 500 Hz limit (v2). [2, 7]

**Golay code**: a classic error-correcting code that protects the FICH header. [6]

**Greedy**: an approach that makes the best-looking choice at each step without planning ahead. See bit allocation. [4]

### H
**Harmonics**: sine waves at whole-number multiples of the pitch. A voiced sound is the sum of its harmonics. [2]

**Held out**: test data kept out of training, so the test is fair. sotto's codebook is tested on 16 held-out voices. [4, 7]

**Hold and fade**: the two halves of sotto's concealment: *hold* repeats the last good frame for a short time, *fade* then lowers it step by step. [6]

### I
**Interleaving**: see spreading.

### K
**k-means**: a training method for finding a good codebook. Start with random entries, put each training example with its nearest entry, move every entry to the average of its group, and repeat until nothing changes. sotto trains each VQ stage this way, then re-tunes the stages together (`ShapeMSVQ`). [4]

### L
**L**: the number of harmonics below 4,000 Hz: L = ⌊π ÷ Wo⌋. [2]

**LibriSpeech**: a large collection of audiobook recordings (CC BY 4.0). Part of the training speech for sotto's codebook. [4]

**Listening round**: one batch of blind A/B tests played to listeners (members of a radio club). Each round includes the original clip next to every pair, and a null pair. [7]

**LLR (log-likelihood ratio)**: a soft bit: a number saying how sure the receiver is that a bit is 0 (positive) or 1 (negative). Bigger means more sure. [6]

**Lookahead**: how far into the future an encoder must see before deciding about the present. sotto's tracker can search the whole recording, but tests showed 80 ms of look-ahead loses only 0.003 PESQ, so the real-time version will use 80 ms (`lag` in `track_pitch_voicing()`). See Viterbi algorithm. [2, 7]

**LPC / LPC-10**: linear prediction. Codec 2 2400's way of describing the envelope, with 10 numbers that define a smooth curve. The quantization ladder showed it's Codec 2's biggest quality loss for male voices. [3, 7]

**LSP**: "line spectral pairs". Another way of writing the 10 LPC numbers that is easier to round off safely. Codec 2 2400 quantizes LSPs. [7]

### M
**M-best search**: a shortcut for searching a multistage VQ. Instead of keeping only the single best choice after each stage, keep the 8 best so far and pick the overall winner at the end. It finds nearly the best combination without trying all 17 billion. [4]

**Mel scale**: a frequency scale that matches human hearing, finer at low frequencies and coarser at high ones. sotto's 20 envelope points are evenly spaced on it, from 200 to 3,700 Hz. [3]

**Memoryless**: each frame can be decoded on its own, without the frames before it. sotto is memoryless so that one lost frame can't damage the next ones. (The voicing edge code peeks at the frame before, but only to choose between two orderings.) [4]

**Mixed voicing (mixed excitation, MBE, MELP)**: letting a sound be partly buzz and partly hiss, like "z" or "v". Since v3.2, sotto has three kinds of frame: **U** (unvoiced, all noise), **V** (voiced, all harmonics) and **M** (mixed: harmonics below 1,000 Hz, noise above). A frame becomes M when it's voiced but its harmonics fit poorly below 1,000 Hz (`voicing_classes()`). MBE and MELP split voicing into more bands. [2, 5]

**Multistage VQ (MSVQ)**: a vector quantizer done in steps. Stage 1 picks the closest codebook entry; stage 2 picks an entry that best corrects what stage 1 got wrong; stage 3 corrects what's left. sotto's shape quantizer uses 3 stages of 12, 11 and 11 bits (`ShapeMSVQ`). [4]

**Model**: the vocoder's description of one 10 ms frame: `Wo`, `L`, `A`, `phi` and `voiced`. Stored in the `MODEL` record type in `sim/vocoder_lab.py`. [2]

### N
**newamp1**: an experimental Codec 2 mode that introduced the rate-K mel envelope and the formant postfilter that sotto builds on. [3]

**NLP**: "non-linear pitch". Codec 2's pitch tracker. sotto v0 used it as is; later versions start from its answers and correct octave errors. [2]

**Null pair**: a listening-test pair where A and B are the same clip. A careful listener calls it a tie; a listener who picks a winner is probably guessing elsewhere too. [7]

### O
**Octave error**: a pitch tracker reporting double or half the true pitch. [2]

**Odd/even check (sub-octave check)**: a test added to the tracker in v3.3. If a pitch candidate's odd harmonics (3rd, 5th, 7th...) are much weaker than its even ones, it's probably half the true pitch, so it gets a penalty. `odd_even_db()` in `sim/sinusoid.py`. [2]

**Oracle**: in an experiment, a helper that uses the true, perfect value instead of an estimate or a rounded value. Comparing with and without an oracle shows how much that part costs. [7]

**Oracle ladder**: see quantization ladder.

**Oracle lab**: `sim/vocoder_lab.py`: tools for editing Codec 2's model in Python and listening to the result. [7]

### P
**Payload**: the part of a frame that carries the actual data (as opposed to sync and headers). In System Fusion, 720 bits per 100 ms. [6]

**PESQ**: "perceptual evaluation of speech quality". A computer score that predicts how listeners would rate quality, from about 1 (bad) to 4.5 (perfect). [7]

**Phase (phi)**: `phi` in the model. Where in its cycle a sine wave starts. sotto doesn't send phases; the decoder invents them. [5]

**phase0 (synthetic phase)**: Codec 2's way of inventing phases: imagine each vocal-cord pulse as a click played through the envelope filter. Unvoiced frames get random phases. [5]

**Pitch (F0)**: how fast the vocal cords buzz, in Hz. About 85–155 Hz for men and 165–255 Hz for women. [2]

**Pitch oracle**: an oracle test for pitch: the decoder is given the true (or carefully checked) pitch instead of the rounded or estimated one, to measure how much pitch errors cost. [7]

**Pitch tracker (pitch estimator)**: the part of the encoder that measures pitch. Errors where it reports double or half the true pitch are called **octave errors**. See sotto tracker. [2]

**pYIN**: a well-known offline pitch tracker, used as a reference to count Codec 2's octave errors. Not perfect either. [2]

**PN9**: a fixed pseudo-random bit pattern that sotto mixes into the payload (scrambling). [6]

**Postfilter (Codec 2)**: Codec 2's `--postfilter`: a zero-bit trick that gives random phases to harmonics quieter than the background noise, so noise sounds like noise. [5]

**Puncturing**: deleting some of a code's output bits in a fixed pattern, to make exactly the right number of bits. sotto's code makes 3 bits per input bit and punctures down to 18 for every 7 ("rate 7/18"). [6]

**Predictive quantizer**: one that guesses each frame from the previous one and sends only the difference. Tried twice (the `SottoV1` and `SottoV2P` classes in the code, the second with regular resets) and rejected both times, because a lost frame throws the decoder's guesses off for several frames. [4]

### Q
**Quantization**: rounding a number to one of a small set of allowed values, so it can be sent as a few bits. [4]

**Quantization error**: the difference between the true value and the rounded one. [4]

**Quantization ladder**: an experiment that starts with a perfect (all-oracle) vocoder and makes one piece realistic per step (made-up phases, then the LPC envelope, then rounding...). The drop at each rung shows what that piece costs. The code calls it the oracle ladder (`sim/oracle_ladder.py`). [7]

**Quantizer**: the rule for rounding. A **uniform** quantizer has equal steps (sotto's energy); a **log-uniform** one has equal *ratios* between steps (sotto's pitch). [4]

### R
**Rate-K envelope**: the envelope sampled at K fixed frequencies (K = 20 in sotto), instead of at the harmonics. "Rate-K" as opposed to "rate-L", the L harmonic amplitudes. `to_rate_k()`, `from_rate_k()`, `KFREQ`. [3]

**Rayleigh fading**: the rapid dips in signal strength in a moving vehicle, caused by reflections adding and canceling. [6]

**RRC filter**: "root-raised-cosine". The filter that smooths the C4FM hops at the transmitter and matches them at the receiver. [6]

### S
**Sample / sample rate**: one measurement of the microphone signal. sotto uses 8,000 per second. [1]

**Scrambling**: mixing the bits with a known pseudo-random pattern (PN9) to avoid long runs of one symbol. Undone at the receiver. [6]

**SDR**: software-defined radio. A radio whose signal processing is done in a computer. The softmodem can use one. [6]

**Shape**: the 20-point envelope with its average removed, so only the ups and downs are left. [3]

**Shape quantizer**: the part of sotto that squeezes the envelope shape into 34 bits. Since v3 it's a 3-stage vector quantizer (`ShapeMSVQ`, codebook in `sim/data/shape_msvq_34.npz`) with 45% less error than before. Up to v2 it was `ShapeQ`, a scalar quantizer: it took the DCT of the shape, gave each cosine-wave size its own uniform quantizer with a trained step size, and split the bits by greedy allocation (5, 4, 3, 3, 2, ... bits). [4]

**Silence (true silence)**: since v3, energy code 0 tells the decoder to output nothing at all, instead of a faint buzz or hiss. Listeners had heard a "floor" of noise between words. [4]

**sotto tracker**: sotto's joint pitch and voicing tracker (`track_pitch_voicing()` in `sim/sinusoid.py`). For every 10 ms frame it lists "unvoiced" plus several pitch candidates (Codec 2's estimates nearby, doubled and halved), adds up six kinds of cost (bad fit, low pitch, disagreeing with Codec 2's voicing, switching, jumping, missing odd harmonics), and uses the Viterbi algorithm to pick the cheapest path. Pitch is kept between 70 Hz (for doubled and halved candidates) and 500 Hz. v1 had a simpler pitch-only version, `track_pitch()`. [2]

**sotto v0 to v3.5**: versions of the sotto encoder, all with the same 48-bit, 20 ms frame. v0: the 20-point envelope. v1: the octave-correcting pitch tracker (`SottoV0(pitch="tracked")` in the code). v2: joint pitch and voicing tracking, and a 500 Hz pitch limit. v3: the trained vector quantizer and true silence. v3.1: the tail rule. v3.2: mixed voicing. v3.3: odd/even check. v3.4: concealment in the decoder. v3.5: lighter postfilter (1.35) and short concealment; `SottoV35` in `sim/vocoder_lab.py`. [1, 2, 4, 6]

**Sine wave**: the smoothest possible repeating wiggle, with a frequency, amplitude and phase. [2]

**Sinusoidal model**: describing speech as a sum of sine waves (the harmonics). Codec 2 and sotto are both sinusoidal vocoders. [2, 5]

**Softmodem**: sotto's software modem (`modem/`), which sends and receives System Fusion frames through a sound card or SDR. [6]

**Soft bits**: see LLR.

**Speech Commands**: a large collection of short spoken words from thousands of people (CC BY 4.0). Part of the training speech for sotto's codebook, and the source of the counting clips used for testing. [4, 7]

**Springs**: listeners' word for the twangy sound when a decoder holds a buzzy vowel steady through a lost signal. v3.5's short concealment avoids it. [6]

**Spectrogram**: a picture of sound with time across, frequency up, and loudness as darkness. [2]

**Spectrum**: loudness at each frequency at one moment. [2]

**Spreading (interleaving)**: shuffling bit positions so each vocoder frame's bits are sprinkled across the whole 100 ms radio frame. Then one short fade damages a little of every frame instead of all of one frame. [6]

**Sweep**: an experiment that tries a range of values for one setting (like the postfilter strength) on many voices and keeps the best. [7]

**Step size**: the distance between two neighboring levels of a uniform quantizer. [4]

**Sync**: a fixed bit pattern at the start of each radio frame that the receiver searches for. [6]

**Synthesis**: the decoder's last job: turning the model back into sound by adding up sine waves. [5]

**System Fusion (YSF)**: Yaesu's digital radio standard. sotto uses its C4FM signal and frame layout, carrying sotto voice instead of AMBE. [6]

### T
**Tail rule**: a voicing clean-up from v3.1. A voiced frame with a weak harmonic fit that is more than 20 dB quieter than the last 300 ms is played as unvoiced, so the fading end of a "v" doesn't buzz on as "uh". `unvoice_tails()`. [2]

**Tail-biting**: a way of running a convolutional code on a block so the end wraps around to the start, wasting no bits on start-up and shut-down. [6]

**Training**: tuning a quantizer's settings by running it on lots of real speech. The old scalar quantizer trained step sizes and bit allocation (`training_set()`); the vector quantizer's codebooks are trained with k-means on about 480,000 frames from more than 600 speakers. [4]

### U
**Unvoiced**: a sound made by hissing air with no vocal-cord buzz, like "s", "f", "sh", or whispering. [2]

### V
**Viterbi algorithm**: a method for finding the best path through a long chain of choices without trying every path. The receiver uses it to decode the convolutional code, and sotto's tracker uses it to choose pitch and voicing. A **fixed-lag** Viterbi decides each frame after looking only a fixed time ahead (80 ms for sotto) instead of waiting for the end. [2, 6]

**Vector quantizer (VQ)**: rounding a whole list of numbers at once, by picking the closest pattern from a codebook and sending its number. It can learn which combinations really happen in speech, so it wastes fewer bits than rounding each number separately. [4]

**Vocoder**: "voice coder". A codec that sends a description of how a voice is being made, instead of the sound wave itself. [1]

**Voiced**: a sound with vocal-cord buzz, like vowels, "m", "n". [2]

**Voiced fricative**: a sound that is buzz and hiss at once, like "v", "z" or the "s" in "measure". sotto sends these as mixed frames. [2]

**Voicing**: whether a frame is buzz, hiss or both. sotto sends 2 bits per 20 ms frame as one of four codes: U U, V V, M M, or an edge between U and M. Up to v3.1 the 2 bits were one yes/no for each 10 ms half. In the model it's the `voiced` value: 0, 1, or 2 and up for mixed (the harmonic where the noise starts). [2, 4]

### W
**Wo** ("omega-zero"): the pitch written as an angle per sample: Wo = 2π × pitch ÷ 8000. sotto sends it with 7 bits, from 50 to 500 Hz in steps of 1.83% (400 Hz and 1.65% in v0 and v1). [2, 4]
