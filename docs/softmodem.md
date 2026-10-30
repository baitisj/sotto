# sotto softmodem

*Written 2026-10-30. Code: `modem/`. Tests: `tests/test_modem.py`.*

The softmodem lets people take part without C4FM hardware. It sends and receives YSF (System Fusion) frames carrying sotto voice in one of two ways:

- **through an FM radio's 9600 (flat) data port**, using a computer or Pi sound card, or
- **with an SDR**, using complex IQ.

It is plain Python (numpy and scipy). It is a reference implementation and test bench, not yet a real-time program.

## Using it

```sh
./tools/build_codec2.sh                               # c2enc / c2dec into build/codec2/src
build/codec2/src/c2enc 2400 speech.raw voice.bit      # 8 kHz 16-bit raw speech in
python -m modem tx voice.bit tx.flac --src N0CALL     # baseband audio (FLAC or WAV) for the data input
python -m modem rx rx.flac back.bit                   # discriminator audio from the data output
build/codec2/src/c2dec 2400 back.bit out.raw
python -m modem tx voice.bit tx.cf32 --iq 240000      # FM-modulated IQ for an SDR transmitter
python -m modem rx rx.cf32 back.bit --iq 240000       # IQ from an SDR receiver
```

`rx` finds the level, polarity and DC offset by itself. It accepts any sample rate, including 44.1 kHz. It prints how many frames it concealed and the callsigns from the header.

## Hardware paths

| Setup | TX | RX | Notes |
|---|---|---|---|
| FM radio with a 9600 data port + sound card | sound card out → data in (direct to the modulator) | data out (discriminator) → sound card in | The common 6-pin mini-DIN DATA jack. Use the radio's 9600 setting, not 1200: the 1200 path is filtered and pre-emphasised. Sound cards block DC, which the receiver handles (tested with a 30 Hz high-pass). |
| SDR | HackRF or similar plus an amplifier, `--iq` | RTL-SDR or similar, `--iq` | Needs a licensed operator and proper filtering for TX. RX alone is a cheap way to monitor. |
| Mic/speaker audio only | no | no | C4FM doesn't survive voice-band filtering and pre-emphasis. These users would need a slower audio-band modem, which our waveform race showed is weaker. |

## What's on the air

The standard YSF frame: 100 ms = 480 symbols = sync (40 bits), FICH (200), payload (720). We write the framing from the published layout, and our Golay table matches the one used by existing open YSF software for all 4096 entries.

| Frame | FICH | Payload |
|---|---|---|
| Header | FI = header, DT = voice FR, DG-ID | CSD1 = destination + source callsigns, CSD2 (Data FR coding, as Fusion radios send) |
| Voice | FI = communications, DT = voice FR, FN 0–6 | **sotto VW payload** (below) |
| Terminator | FI = terminator | same as header |

**sotto VW payload**:

1. Five 48-bit Codec 2 2400 frames (100 ms) each get a CRC-8, giving 280 bits.
2. A tail-biting K=7 convolutional code (133, 171, 165), punctured to rate 7/18, turns those into 720 bits.
3. The coded bits are spread across the whole 100 ms frame, so each vocoder frame's bits sit 3 ms apart.
4. The result is scrambled with a PN9 sequence, which keeps the signal free of DC for sound cards.

The FICH's unused bit 7 of byte 2 marks sotto frames. That choice is **provisional**.

Two research payloads share the same code, for comparison: `dn_conv` (DN slots, rate 7/13 plus CRC) and `dn_rep` (DN slots with Fusion's own AMBE protection: 27 bits sent three times, the rest unprotected).

## Receiver

1. **Filtering and sync detection.** A root-raised-cosine matched filter, then the 20-symbol sync is correlated against every sample. The correlation is normalised, so level and DC don't matter, and a negative peak means inverted audio.
2. **Hunting.** A peak is accepted only if the FICH then decodes (Golay plus CRC-16), which rejects false syncs.
3. **Locked (flywheel).** The next frame is expected 480 symbols later, within ±5 samples. The receiver re-times only on a strong sync peak or a good FICH. In a fade it coasts, which fixed early timing jumps caused by fades.
4. **Level fit.** Each frame gets a decision-directed least-squares fit of scale, DC and DC drift. It starts from both the sync fit and the previous frame's fit and keeps whichever gives the smaller residual.
5. **Soft bits** come from max-log over the four levels, with noise variance tracked over 24 symbols.
6. **Placement and concealment.** Vocoder frames are placed by time, so lost frames become erasures. CRC failures are replaced by the last good frame (up to 3 times), then by a near-silent Codec 2 frame.

## Tests (22, all passing)

`python -m pytest tests` takes about 20 s. The tests cover:

- **Framing:** Golay values matching the reference table, Golay correcting 3 errors, the CRC-16 check value, FICH and header round trips with bit errors, and the tail-biting code.
- **Payloads:** a round trip for every payload scheme, and the CRC rejecting garbage.
- **Full audio path:**
  - bit-exact loopback for all schemes;
  - sound card at a quiet level, inverted, with a DC offset;
  - AC coupling at 30 Hz;
  - 44.1 kHz with +100 ppm clock error;
  - 48 kHz with −200 ppm clock error;
  - a noisy FM channel at 50 dB-Hz;
  - fading at 446 MHz / 60 km/h, checking that every wrong frame is flagged by the CRC;
  - the SDR IQ path with 300 Hz mistuning and noise;
  - a command-line round trip at 44.1 kHz.

## Interoperability findings (important)

- **MMDVM hotspots and repeaters rewrite voice payloads.** MMDVMHost "regenerates" the voice FEC of every frame it relays, on both the RF and network sides: it re-votes DN triplets and re-encodes the Golay/Hamming FEC of the IMBE code used in VW. A sotto payload passing through it would be corrupted. This **corrects** what I said in the waveform race: sotto will *not* cross Pi-Star or MMDVM networks unchanged. The fix is a small MMDVMHost change that skips regeneration when the sotto flag is set, or having the softmodem talk to YSF reflectors directly. YSFReflector itself only forwards frames.
- **Not yet checked against a real Fusion radio.** We have no off-air capture yet. The things to confirm are:
  - the transmit pulse shape: we use RRC at both ends; the spec-style filter is raised-cosine with integrate-and-dump;
  - deviation: ±1800 Hz outer symbols, about 3.2 kHz peaks with RRC overshoot;
  - symbol polarity;
  - whether a stock radio mutes or squawks on sotto frames;
  - whether it needs Fusion's own VW frame-0 layout, where frame 0 carries data in its first 3 sections.
- **DN slot size correction.** A DN voice slot is 104 bits per 20 ms, not the 72 the waveform race assumed. See the correction note in `waveform-race.md`.

## Next steps

1. An off-air capture from a real Fusion radio: RTL-SDR IQ, or the FTM-300's data port. That lets us check sync, FICH and timing against Yaesu's modulator.
2. A real-time front end: a sound-card stream and push-to-talk, ideally in C so it can share code with the DSP port.
3. A patch to MMDVMHost to pass sotto frames through.
