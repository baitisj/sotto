# Waveform race: is leaving C4FM worth it?

*Written 2026-10-30. Code: `sim/waveforms.py`, `sim/waveform_race.py` and `sim/vw_race.py`. Results: `docs/results/wave_race_results.json`.*

## Short answer

**There's no clear win from a new waveform. The big win is giving voice more of the C4FM channel.** If we keep Yaesu's C4FM framing but carry sotto in the **VW (full-rate) voice slot** with a rate-1/3 code, we beat every custom waveform I tried on noise and fading. Against today's DN slot it gains about **6 dB** at the same transmit power. The only place a custom waveform wins is large delay spread (100 µs and up), where slow 4FSK holds on longer. Delay spread that large is rare on 2 m and 70 cm outside simulcast systems.

So compatibility and performance point the same way: **stay C4FM, use the VW slot.**

## Setup

The radio's DSP can only drive the FM VCO and only hears the discriminator (see the hardware summary). So every candidate is a baseband frequency waveform sent through the same chain: FM, then flat Rayleigh or two-path fading, AWGN, a ±6 kHz IF filter, and the discriminator. All candidates carry the same **2400 bps** vocoder stream (48 bits / 20 ms) through a K=7 convolutional code and a 4-frame (80 ms) interleaver, at **equal transmit power**: the x-axis is C/N0 in dB-Hz. Metrics: class-A bad frames (any of the 24 most sensitive bits wrong) and class-B BER. 2000 frames (40 s) per point.

| Entry | What it is | Coded rate on air |
|---|---|---|
| `c4fm_dn` | C4FM at 4800 baud. Voice gets 36 of every 96 symbols (Fusion DN slot), rate-2/3 code | 3600 of 9600 bps |
| `c4fm_vw` | C4FM at 4800 baud. Voice gets 72 of 96 symbols (Fusion VW slot), **rate-1/3** code | 7200 of 9600 bps |
| `fsk4_1800` | 4FSK at 1800 baud (±600/±1800 Hz), rate-2/3 code, the whole channel for voice | 3600 bps |
| `fsk2_3600` | 2FSK at 3600 baud (±1800 Hz), rate-2/3 code, the whole channel for voice | 3600 bps |
| `ofdm` | 40-carrier DQPSK in the audio band (400–2350 Hz, 50 Hz spacing, 20 + 2 ms symbols), FM at 1 kHz rms deviation, rate-2/3 code | 3600 bps |

## Results: class-A bad-frame rate

| Condition | DN | **VW** | 4FSK 1800 | 2FSK 3600 | OFDM |
|---|---:|---:|---:|---:|---:|
| AWGN 44 dB-Hz | 92% | **41%** | 61% | 41% | 99% |
| AWGN 46 dB-Hz | 34% | 3.1% | 7.7% | **1.3%** | 34% |
| 146 MHz 30 km/h, 52 dB-Hz | 24% | **6.7%** | 15% | 11% | 31% |
| 146 MHz 30 km/h, 56 dB-Hz | 6.3% | **1.0%** | 4.0% | 1.9% | 14% |
| 146 MHz 60 km/h, 52 dB-Hz | 20% | **2.9%** | 13% | 6.1% | 42% |
| 446 MHz 60 km/h, 52 dB-Hz | 19% | **1.7%** | 18% | 5.4% | 56% |
| 446 MHz 60 km/h, 56 dB-Hz | 3.7% | **0.25%** | 6.1% | 0.65% | 21% |
| 446 MHz 120 km/h, 52 dB-Hz | 24% | **2.4%** | 24% | 6.8% | 65% |
| 2-path 50 µs, 60 dB-Hz | 15% | 0.45% | 2.4% | **0.30%** | 15% |
| 2-path 100 µs, 60 dB-Hz | 83% | 23% | 6.7% | **6.2%** | 62% |
| 2-path 200 µs, 60 dB-Hz | 98% | 84% | **61%** | 84% | 98% |

All 25 conditions, with class-B BER, are in the JSON.

**C/N0 needed for 5% bad frames at 446 MHz / 60 km/h** (read off the table): VW about 50.5 dB-Hz, 2FSK about 52, DN about 57, 4FSK about 57.5, OFDM above 60. **VW beats DN by about 6 dB**. About 4.3 dB of that comes from voice getting 75% instead of 37.5% of the symbols, and the rest from the stronger code.

## Reading it

- **Slower symbols don't buy fading margin.** 4FSK at 1800 baud loses to C4FM-VW by 5–7 dB on fading. With a discriminator receiver the FM threshold dominates, and a deep fade wipes out the same number of milliseconds whatever the symbol rate. Long symbols pay off only against delay spread.
- **OFDM over FM is the worst here.** Below the FM threshold, discriminator clicks are wideband impulses that hit every carrier at once, and differential detection costs another ~3 dB. My OFDM is a naive first version (no pilots, no clipping optimization), but the click problem is fundamental for OFDM sent through FM. It is the same reason analog FM + Data2G (Data2G's OFDM sent as audio through the radio) needs a good signal. A Data2G rung on this radio wouldn't beat C4FM for voice.
- **Delay spread is the custom waveforms' only niche.** At 100 µs, 2FSK and 4FSK (6–7%) beat VW (23%). At 200 µs everything fails. Mobile delay spread on 2 m and 70 cm is usually under about 5 µs, so this matters mostly for simulcast or mountainous paths.
- **More code beats a cleverer waveform.** A custom waveform also using a 7200 bps channel with a rate-1/3 code would probably land close to VW. But at that point it is C4FM without the compatibility.

## Caveats

- The receiver is a plain discriminator with perfect timing and sync, with no AFC or impulse noise. The absolute C/N0 values are approximate (my C4FM gets 1% raw BER at ~50.5 dB-Hz; the radio's 0.19 µV spec implies something similar). The comparisons are what count.
- CPM in the strict sense (partial-response pulses with coherent MLSE detection) isn't possible here, because the DSP never sees the RF phase. With a discriminator, "CPM" comes down to the choice of pulse shape, which changes the spectrum much more than the error rate.
- VW uses twice the coded bits. That's the point, but it does tie up the whole frame: there's no room left for DN's data channel (GPS position, text).

## Compatibility (WIRES-X, Fusion repeaters)

Arguments **for** keeping Yaesu's C4FM framing (sync, FICH, VW slot):
1. **It's also the best performer** (above). Compatibility costs nothing in link quality.
2. **The modem already exists.** If WS3 lets us patch only the vocoder inside Yaesu's DSP image, the proven sync, timing, AFC and FICH handling stay. That's the smallest change that gets sotto on the air.
3. **Open networking for free.** MMDVM hotspots, Pi-Star, YSFReflector and similar demodulate C4FM to bits and relay frames *without decoding the voice*. sotto-in-YSF frames should cross those networks unchanged. (I haven't checked this for Yaesu's own WIRES-X servers or HRI-200 nodes, which may handle voice differently.)
4. **Coexistence.** Other Fusion radios read the FICH and DG-ID, so they stay muted, and repeaters recognise the signal as digital. A foreign waveform sounds like noise to everyone else and may trigger AMS repeaters into odd states.
5. **Open tools for testing.** The same open C4FM demodulators (MMDVM, SDR decoders) can capture off-air frames and measure bit errors using the known sync and FICH CRC. That gives us the real burst-error data we're missing.

Arguments **against**, or limits:
1. **No one else can hear us.** Stock Fusion radios will decode sotto frames as garbage AMBE/IMBE. An AMS repeater that transcodes digital to FM may broadcast that garbage, and a DR-2X might regenerate or re-encode VW frames. That has to be tested on a repeater before anyone uses it there.
2. **We inherit C4FM's delay-spread limit** (about 25–50 µs), plus Fusion's fixed 100 ms framing for interleaving and superframes.
3. **VW gives up the DN data channel.** If position or text data matters, DN with a better code is the alternative, at about 6 dB worse.

**Recommendation:** keep C4FM and the YSF framing, and put sotto in the VW slot. Treat WIRES-X as a bonus to test, not a requirement. Revisit a custom waveform only if simulcast or heavy-multipath use becomes a goal.
