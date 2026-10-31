---
title: "Glossary"
---

# Glossary

[Course home](README.md)

Terms used in the sotto code, the design notes in `docs/`, and this course, in plain words. Names in `code font` are how the term appears in the code. The chapter where each idea is explained is in brackets.

### A
**A (amplitudes)**: `A` in the model. The loudness of each harmonic in one 10 ms frame. `A[1]` is the first harmonic, `A[L]` the last. [2]

**Analysis**: the encoder's first job: measuring pitch, voicing and harmonic amplitudes from the microphone signal. sotto v0 uses Codec 2's analysis (`analyse()` in `sim/vocoder_lab.py`). [2]

**AMBE / AMBE+2**: the closed, licensed vocoder used by Yaesu System Fusion and other digital radios. sotto aims to match its quality with open code.

### B
**Bit**: a single 0 or 1. With n bits you can send one of 2ⁿ messages. [1, 4]

**Bit allocation**: deciding how many bits each number in a frame gets. sotto's shape quantizer uses **greedy bit allocation**: it hands out bits one at a time, each to whichever number it helps most. [4]

**Bit rate**: bits per second. sotto's vocoder runs at 2,400 bits per second; the radio carries 9,600. [1, 6]

### C
**C4FM**: "4-level FM". The radio signal sotto sends: the frequency hops between four values (±600 and ±1,800 Hz) 4,800 times a second, carrying 2 bits per hop. [6]

**C5517**: the TI digital signal processor (DSP) chip inside the Yaesu FTM-300D radio, where sotto is meant to run one day.

**c2sim, c2enc, c2dec**: Codec 2's command-line programs. `c2sim` runs the analysis and synthesis separately, so experiments can edit the model in between (`--modelout`, `--modelin`). `c2enc` and `c2dec` are the full Codec 2 encoder and decoder. [7]

**Codec**: short for coder-decoder. Any system that packs data into bits and unpacks it again. A vocoder is a codec for voice.

**Codec 2**: an older open-source vocoder by David Rowe. sotto borrows its pitch tracker, voicing detector and synthesizer, and keeps a copy of its source code in `codec/codec2/` (under its own LGPL license). [1]

**Concealment**: hiding a lost frame from the listener, by repeating the last good frame (up to 3 times) and then fading to silence. [6]

**Convolutional code**: an error-correcting code in which every output bit mixes the last several input bits (7 for sotto: "K = 7"). Decoded with the Viterbi algorithm. [6]

**CRC (CRC-8, CRC-16)**: "cyclic redundancy check". A short fingerprint (8 or 16 bits) computed from a block of data, which lets the receiver tell whether the block arrived intact. It detects errors but doesn't fix them. [6]

### D
**dB (decibel)**: a scale for loudness or power that works by ratios. +10 dB is 10 times the power; +6 dB is about 4 times; +3 dB is about 2 times. [3, 4]

**dB-Hz (C/N₀)**: how strong a radio signal is compared with the noise, measured per hertz of bandwidth. In the test conditions, 52 dB-Hz is a weak signal and 56 dB-Hz a somewhat better one. [6]

**DCT (discrete cosine transform)**: rewriting a list of numbers as the sizes of cosine waves added together. sotto applies it to the 20-point envelope shape, so most of the shape ends up in the first few numbers. JPEG uses the same idea. `DCT` in the code is the 20 × 20 table. [3]

**Decimate / interpolate**: decimating means keeping only every second frame (sotto sends one analysis per 20 ms out of two). Interpolating means filling the missing frames in with values halfway between their neighbors. `decimate_interp()`, `interp_wo()`. [4]

**Decoder**: the receiving half of a codec. sotto's decoder turns 48 bits into 20 ms of sound. `SottoV0.decode()`. [5]

**Discriminator**: the part of an FM receiver that turns frequency back into a voltage. The softmodem reads its output. [6]

**DN / VW**: two voice layouts in System Fusion. DN ("digital narrow", also called V/D mode 2) uses part of each frame's payload for voice; VW ("voice wide", also called voice full-rate) uses all 720 payload bits. sotto uses the VW slot, protecting its voice much more strongly. [6]

**Doppler (fd)**: how fast the fading changes, which depends on the radio frequency and how fast you're moving. 446 MHz at 60 km/h gives about 25 Hz; 146 MHz at 30 km/h about 4 Hz. [6]

### E
**Encoder**: the sending half of a codec. `SottoV0.encode()`. [1]

**Encoder race**: an experiment where two encoders (Codec 2 2400 and sotto v0) send through the identical radio chain with the same fading, and are scored the same way. `sim/encoder_race.py`. [7]

**Energy**: how loud a frame is: the sum of the harmonics' powers, in dB. Sent with 5 bits from 10 to 80 dB. [4]

**Envelope (spectral envelope)**: the smooth outline across the tops of the harmonics. It describes the shape of the throat and mouth, and carries most of the words. [3]

**Erasure**: a bit or frame the receiver knows is missing or unreliable, as opposed to one that is silently wrong. [6]

**ESTOI**: a computer score that predicts intelligibility (how many words a listener would get), from 0 to 1. [7]

### F
**FEC (forward error correction)**: extra bits added before sending so the receiver can fix errors itself, without asking for a resend. sotto's FEC is a convolutional code. [6]

**FICH**: "frame information channel". The 200-bit header in every System Fusion frame that says what kind of frame it is. sotto marks its frames with one spare bit in the FICH (a provisional choice). [6]

**Flywheel**: the receiver's habit of expecting the next frame exactly 100 ms after the last, so it keeps its place through a fade. [6]

**Formant**: a loud bump in the envelope, caused by a resonance of the throat and mouth. Different vowels have formants in different places. [3]

**Formant postfilter**: sotto's decoder step that stretches the envelope's peaks and valleys by 1.5 (in dB) to undo blurring from quantization. `postfilter_rk()`. Not the same as Codec 2's postfilter. [5]

**Frame**: a chunk of data handled as one unit. A sotto vocoder frame is 20 ms and 48 bits. A System Fusion radio frame is 100 ms and 960 bits, carrying 5 vocoder frames. The analysis also works in 10 ms frames, sometimes called subframes. [1, 6]

**Frequency**: how many times per second something repeats, in hertz (Hz). [2]

### G
**Golay code**: a classic error-correcting code that protects the FICH header. [6]

**Greedy**: an approach that makes the best-looking choice at each step without planning ahead. See bit allocation. [4]

### H
**Harmonics**: sine waves at whole-number multiples of the pitch. A voiced sound is the sum of its harmonics. [2]

**Held out**: test data kept out of training, so the test is fair. [4]

### I
**Interleaving**: see spreading.

### L
**L**: the number of harmonics below 4,000 Hz: L = ⌊π ÷ Wo⌋. [2]

**LLR (log-likelihood ratio)**: a soft bit: a number saying how sure the receiver is that a bit is 0 (positive) or 1 (negative). Bigger means more sure. [6]

**LPC / LPC-10**: linear prediction. Codec 2 2400's way of describing the envelope, with 10 numbers that define a smooth curve. The quantization ladder showed it's Codec 2's biggest quality loss for male voices. [3, 7]

**LSP**: "line spectral pairs". Another way of writing the 10 LPC numbers that is easier to round off safely. Codec 2 2400 quantizes LSPs. [7]

### M
**Mel scale**: a frequency scale that matches human hearing, finer at low frequencies and coarser at high ones. sotto's 20 envelope points are evenly spaced on it, from 200 to 3,700 Hz. [3]

**Memoryless**: each frame can be decoded on its own, without the frames before it. sotto v0 is memoryless so that one lost frame can't damage the next ones. [4]

**Mixed voicing (MBE, MELP)**: describing voicing separately in several frequency bands, so a sound can be partly buzz and partly hiss (like "z"). Not in v0; on the to-do list. [2]

**Model**: the vocoder's description of one 10 ms frame: `Wo`, `L`, `A`, `phi` and `voiced`. Stored in the `MODEL` record type in `sim/vocoder_lab.py`. [2]

### N
**newamp1**: an experimental Codec 2 mode that introduced the rate-K mel envelope and the formant postfilter that sotto v0 builds on. [3]

**NLP**: "non-linear pitch". Codec 2's pitch tracker, which sotto v0 uses. [2]

### O
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

**Pitch tracker (pitch estimator)**: the part of the encoder that measures pitch. Errors where it reports double or half the true pitch are called octave errors. [2]

**PN9**: a fixed pseudo-random bit pattern that sotto mixes into the payload (scrambling). [6]

**Postfilter (Codec 2)**: Codec 2's `--postfilter`: a zero-bit trick that gives random phases to harmonics quieter than the background noise, so noise sounds like noise. [5]

**Puncturing**: deleting some of a code's output bits in a fixed pattern, to make exactly the right number of bits. sotto's code makes 3 bits per input bit and punctures down to 18 for every 7 ("rate 7/18"). [6]

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

**Shape quantizer**: `ShapeQ`. The part of sotto that rounds the envelope shape into 34 bits: it takes the DCT of the shape, gives each cosine-wave size its own uniform quantizer with a trained step size, and splits the bits by greedy allocation (5, 4, 3, 3, 2, ... bits). [4]

**Sine wave**: the smoothest possible repeating wiggle, with a frequency, amplitude and phase. [2]

**Sinusoidal model**: describing speech as a sum of sine waves (the harmonics). Codec 2 and sotto are both sinusoidal vocoders. [2, 5]

**Softmodem**: sotto's software modem (`modem/`), which sends and receives System Fusion frames through a sound card or SDR. [6]

**Soft bits**: see LLR.

**Spectrogram**: a picture of sound with time across, frequency up, and loudness as darkness. [2]

**Spectrum**: loudness at each frequency at one moment. [2]

**Spreading (interleaving)**: shuffling bit positions so each vocoder frame's bits are sprinkled across the whole 100 ms radio frame. Then one short fade damages a little of every frame instead of all of one frame. [6]

**Step size**: the distance between two neighboring levels of a uniform quantizer. [4]

**Sync**: a fixed bit pattern at the start of each radio frame that the receiver searches for. [6]

**Synthesis**: the decoder's last job: turning the model back into sound by adding up sine waves. [5]

**System Fusion (YSF)**: Yaesu's digital radio standard. sotto uses its C4FM signal and frame layout, carrying sotto voice instead of AMBE. [6]

### T
**Tail-biting**: a way of running a convolutional code on a block so the end wraps around to the start, wasting no bits on start-up and shut-down. [6]

**Training**: tuning a quantizer's settings (step sizes, bit allocation) by running it on lots of real speech. `training_set()`. [4]

### U
**Unvoiced**: a sound made by hissing air with no vocal-cord buzz, like "s", "f", "sh", or whispering. [2]

### V
**Viterbi algorithm**: the method the receiver uses to decode the convolutional code, by finding the input sequence that best explains the received soft bits. [6]

**Vocoder**: "voice coder". A codec that sends a description of how a voice is being made, instead of the sound wave itself. [1]

**Voiced**: a sound with vocal-cord buzz, like vowels, "m", "n". [2]

**Voicing**: the voiced-or-unvoiced decision. sotto sends one bit per 10 ms (`voiced`). [2]

### W
**Wo** ("omega-zero"): the pitch written as an angle per sample: Wo = 2π × pitch ÷ 8000. sotto sends it with 7 bits, from 50 to 400 Hz in steps of 1.65%. [2, 4]
