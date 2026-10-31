# sotto in C

A C port of the sotto v3.5 codec (`sim/vocoder_lab.py`, class `SottoV35`), floating point.
It encodes 8 kHz speech into 48-bit frames every 20 ms (2400 bit/s) and decodes them back,
with the same bits as the Python model.

The port reuses Codec 2's sinusoidal analysis and synthesis by linking `libcodec2` (LGPL-2.1,
built from `codec/codec2/` by `tools/build_codec2.sh`). The code in this directory is MIT.

## Build and run

```sh
tools/build_codec2.sh          # once: builds build/codec2/src/libcodec2.so
make -C c                      # needs python3 + numpy to generate the codebook source
c/sotto_enc in.raw out.bit     # 8 kHz, 16-bit mono raw in; 6 bytes per frame out
c/sotto_dec out.bit dec.raw [good.u8]
```

`good.u8` is optional: one byte per frame, 0 for a frame that failed its CRC. The decoder
conceals those frames as v3.5 does (hold 40 ms, fade 6 dB per 20 ms, silent after 80 ms).

## API

See `sotto.h`. The encoder takes 160 samples per call and returns a frame once its pitch
tracker has 80 ms of look-ahead (the first frame comes on the 6th call); `sotto_enc_flush`
returns the rest at the end of the stream. The decoder returns 160 samples per frame, 20 ms
late, because each odd 10 ms half is interpolated with the next frame.

## Checked against Python

`tools/check_c_port.py` encodes clips with both, and decodes the same bits with both (with a
random 10% frame loss). On 19 voices (`docs/results/c_port_check.json`):

- encoder: 11,170 of 11,173 frames (99.97%) bit-exact. The 3 others are near-ties where the
  pitch tracker can go either way between two octaves: the C side computes spectra with
  Codec 2's float FFT, the Python side in double precision. Mean PESQ is 2.472 for the C
  encoder against 2.475 for Python (with the 10% loss).
- decoder: given the same bits, the C output matches the Python output to about 100 dB SNR,
  concealment included.

## Speed

On one x86 core, the encoder runs at 3% of real time and the decoder at 0.1%. The shape
vector quantizer's M-best search is 90% of the encoder (about 700,000 multiply-adds per
frame with the 12+11+11 codebook). See `docs/c-port.md` for the memory and cycle budget on
the radio's TI C5517 DSP.
