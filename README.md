# (working name)

An open, low-bitrate (2400 bps) voice codec and channel-coding study aimed at
fixed-point DSPs such as the TI C5517 in the Yaesu FTM-300D. The target is
AMBE+2-class quality with better behaviour under bit errors.

## Contents

- `sim/`: a C4FM (4-level FSK over FM) link simulator with Rayleigh and two-path
  fading, plus a first FEC comparison for a 48-bit / 20 ms vocoder frame in a
  72-bit voice slot. Start with `python sim/validate.py`, then `python sim/fec_race.py`.
- `tools/score_samples.py`: PESQ (narrowband) and ESTOI scoring of coded clips
  against the originals.
- `codec/codec2/`: our working fork of Codec 2 (LGPL-2.1), where the oracle experiments and the 2400 bps improvements happen.
- `docs/`: design memos (TWELP survey, Codec 2 improvement plan, FEC race results).

## Rules

- No third-party code with incompatible licenses (for example the STANAG 4591
  reference code). No Yaesu firmware or images.
- Python dependencies: numpy, scipy, soundfile, pesq, pystoi (pesq needs Python 3.11 or older to build).

## License

- Everything outside `codec/` is MIT (see `LICENSE`).
- `codec/codec2/` is a fork of Codec 2 and stays **LGPL-2.1** (see `codec/README.md` and `codec/codec2/COPYING`).
