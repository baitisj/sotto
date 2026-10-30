# Speech through the softmodem: first audio-quality results

*Written 2026-10-30. Code: `sim/audio_race.py`. Results: `docs/results/audio_race.json`.*

## What was run

1. Codec 2 2400, built from `codec/codec2`, encodes the four clean clips (21 s in total).
2. The bits go into YSF frames using one of three payload schemes.
3. The C4FM softmodem modulates them, and the result passes through FM, fading, noise, the IF filter and the discriminator.
4. The **real softmodem receiver** decodes them: sync search, flywheel and level fit, with no genie timing.
5. Codec 2 decodes the output, which is scored against the original with PESQ (narrowband) and ESTOI.

Each point averages 4 clips × 3 fading seeds. With no channel at all, Codec 2 2400 scores **PESQ 2.82, ESTOI 0.69**.

| Scheme | Slot | Protection |
|---|---|---|
| **sotto VW** | VW, 144 bits / 20 ms | CRC-8 + tail-biting K=7 at rate 7/18 |
| DN conv | DN, 104 bits / 20 ms | CRC-8 + tail-biting K=7 at rate 7/13 |
| DN rep | DN, 104 bits / 20 ms | Fusion's AMBE scheme applied to Codec 2: first 27 bits sent 3 times, 21 unprotected |

## Results: PESQ (frame error rate)

| Condition | **sotto VW** | DN conv | DN rep |
|---|---:|---:|---:|
| AWGN 46 dB-Hz | **2.35** (4.4%) | 1.56 (21%) | 1.59 (84%) |
| AWGN 48 dB-Hz | **2.82** (0.1%) | 2.75 (0.6%) | 2.50 (43%) |
| 146 MHz 30 km/h, 52 dB-Hz | **1.69** (11%) | 1.56 (17%) | 1.55 (35%) |
| 146 MHz 30 km/h, 56 dB-Hz | **2.13** (4.1%) | 1.98 (6.0%) | 1.76 (15%) |
| 446 MHz 60 km/h, 48 dB-Hz | 1.34 (32%) | 1.21 (50%) | 1.21 (75%) |
| 446 MHz 60 km/h, 52 dB-Hz | **2.42** (3.7%) | 1.73 (11%) | 1.37 (45%) |
| 446 MHz 60 km/h, 56 dB-Hz | **2.79** (0.1%) | 2.68 (0.9%) | 1.70 (25%) |

ESTOI follows the same order. All values are in the JSON.

## Reading it

- **sotto VW reaches clean-codec quality** (PESQ 2.8) at 48 dB-Hz without fading and at 56 dB-Hz at 446 MHz / 60 km/h. It is the best or tied in every condition.
- **The VW slot gains about 2–3 dB over a well-coded DN slot**, not the 6 dB the waveform race reported. That race gave DN only 72 bits; the real slot has 104. DN conv reaches 1% FER about 3 dB later than sotto VW at UHF.
- **Fusion-style triple repetition is a poor fit for Codec 2.** It leaves 21 bits bare, so it never gets clean (25% FER even at 56 dB-Hz). That is a statement about Codec 2 with that protection, not about AMBE+2, whose decoder is built around it.
- **Slow VHF fading is the hard case.** At 146 MHz and 30 km/h the fades are longer than the 100 ms interleaver, so every scheme loses whole frames. Options: a longer, diagonal interleaver (costs latency), antenna diversity, or better concealment.
- **Concealment barely moves PESQ.** Repeating the last good frame was within ±0.1 of passing bad frames through, and sometimes slightly below. An oracle test on class-A errors only gave the same. The CRC is still worth its ~0.6 dB because it keeps garbage frames, which sound like squawks, out of the decoder and gives a reliable error meter. Whether repeat-and-mute *sounds* better needs ears, not PESQ.

## Listening samples

They are in the project folder, `vocoder/softmodem/samples/`. The clip is ve9qrp, 10 s, run through each scheme at 446 MHz / 60 km/h, 52 dB-Hz and at 146 MHz / 30 km/h, 56 dB-Hz. The folder also has the original and Codec 2 with no channel. The samples are not in the repo, because `*.wav` is ignored.

## Caveats

- The receiver is real, but the channel is the same simplified model as before: a plain discriminator with no AFC and no impulse noise. The absolute dB-Hz values are approximate.
- PESQ is a rough guide for speech with channel errors, and the clips are short (21 s). Differences under about 0.1 are noise.
- The vocoder is stock Codec 2 2400. The improved sotto vocoder would move every column up by the same amount.

## Second run: 15 s male and female voices, FLAC (2026-10-30)

The same test was run on longer clips, stored and rendered as 16-bit FLAC: `python sim/audio_race.py --samples DIR --out docs/results/audio_race_15s.json --render OUT`. The clips:

- **Male 1:** 15 s of ve9qrp, from the long Codec 2 test recording.
- **Male 2:** 15 s of LibriSpeech reader 3436.
- **Female:** LibriSpeech reader 198, 13.9 s. It is the longest clean female clip reachable from the sandbox. The LibriSpeech clips are CC BY 4.0, taken from Ogg copies.

Each point averages 3 seeds. The table shows PESQ after concealment, with ESTOI in brackets.

| Condition | Scheme | FER | Female | Male (mean) |
|---|---|---:|---:|---:|
| No channel | Codec 2 2400 | – | **2.16** (0.73) | **2.88** (0.71) |
| AWGN 48 dB-Hz | sotto VW | 0.0% | 2.16 (0.73) | 2.88 (0.71) |
| | DN conv | 0.5% | 1.99 (0.71) | 2.75 (0.71) |
| | DN rep | 45% | 1.58 (0.62) | 2.17 (0.64) |
| 446 MHz 60 km/h, 52 dB-Hz | sotto VW | 3.5% | 1.69 (0.66) | 2.39 (0.67) |
| | DN conv | 10% | 1.35 (0.52) | 1.79 (0.60) |
| | DN rep | 45% | 1.19 (0.43) | 1.42 (0.48) |
| 446 MHz 60 km/h, 56 dB-Hz | sotto VW | 0.3% | 2.16 (0.73) | 2.75 (0.70) |
| | DN conv | 1.2% | 1.92 (0.70) | 2.52 (0.69) |
| | DN rep | 24% | 1.28 (0.56) | 1.77 (0.59) |
| 146 MHz 30 km/h, 56 dB-Hz | sotto VW | 4.2% | 1.82 (0.66) | 2.02 (0.64) |
| | DN conv | 6.4% | 1.59 (0.63) | 1.78 (0.60) |

All 7 conditions, with per-clip values, are in `docs/results/audio_race_15s.json`.

- **The channel ranking is the same for both voices.** sotto VW is best everywhere, and it reaches no-channel quality at 48 dB-Hz without fading and at 56 dB-Hz at UHF.
- **The female voice loses about 0.7 PESQ in Codec 2 itself, before any channel.** Her ESTOI (intelligibility) is as good as the male voices', so this is a quality gap, not an intelligibility gap. It matches Codec 2's known weakness on higher-pitched voices, where few harmonics carry the spectral envelope. It is a target for the improved vocoder (better spectral envelope at high pitch, MBE-style band voicing). This rests on one female clip from a lossy source, so it needs more female voices to confirm.
