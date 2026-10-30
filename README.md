# sotto

Open 2400 bps digital voice for FM radios: a vocoder, channel coding and a
constant-envelope modem path, built to run on small fixed-point DSPs (first
target: the TI C5517 in the Yaesu FTM-300D).

## Contents

- `modem/`: the **softmodem**. It sends and receives YSF frames carrying sotto voice through a radio's 9600 data port and a sound card, or through an SDR (IQ). `python -m modem tx voice.bit tx.flac`, then `python -m modem rx rx.flac voice.bit`. See `docs/softmodem.md`.
- `tests/`: `python -m pytest tests`.
- `tools/build_codec2.sh`: builds c2enc, c2dec and c2sim into `build/codec2/src`.
- `sim/`: a C4FM (4-level FSK over FM) link simulator with Rayleigh and two-path
  fading; an FEC race (`fec_race.py`); a waveform race (`waveform_race.py`, `vw_race.py`); and an
  end-to-end speech test through the softmodem (`audio_race.py`, needs the Codec 2 build).
- `tools/score_samples.py`: PESQ (narrowband) and ESTOI scoring of coded clips
  against the originals.
- `codec/codec2/`: our working fork of Codec 2 (LGPL-2.1), where the oracle experiments and the 2400 bps improvements happen.
- `docs/`: design memos (TWELP survey, Codec 2 improvement plan, FEC race, waveform race,
  softmodem, audio results).

## Rules

- No third-party code with incompatible licenses (for example the STANAG 4591
  reference code). No Yaesu firmware or images.
- Python dependencies: numpy, scipy, soundfile, pesq, pystoi, pytest (pesq needs Python 3.11 or older to build).

## License

- Everything outside `codec/` is MIT (see `LICENSE`).
- `codec/codec2/` is a fork of Codec 2 and stays **LGPL-2.1** (see `codec/README.md` and `codec/codec2/COPYING`).
