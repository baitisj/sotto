"""The slim sotto 1200 encoder (c/fixed/sotto_fx_slim.c, docs/sotto-slim.md): ordinary
sotto 1200 superframes that the ordinary decoder plays, close to the full encoder's quality,
and the same bits on every machine. Needs make -C c fixed.
SPDX-License-Identifier: MIT"""
import hashlib
import os
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

FX = os.path.join(ROOT, "c", "fixed")
SLIM = os.path.join(FX, "sotto_slim_enc")
FULL = os.path.join(FX, "sotto_enc_fx")
DEC = os.path.join(FX, "sotto_dec_fx")

need = pytest.mark.skipif(not all(os.path.exists(p) for p in (SLIM, FULL, DEC)), reason="needs make -C c fixed")

# SHA-256 of the superframes for the first 6 s of each voice. The encoder is integer only, so
# they are the same on any machine; after a change that is meant to move them, put the new
# values here and say in the PR what PESQ did (docs/sotto-slim.md has the numbers to beat).
GOLDEN = {
    "female_libri198_14s": "9ade02e00ec15ce8d2866668b4bc15c5491064f53d2279867a6d21781f9f4604",
    "male_libri3436_15s": "e448c4d13b930737f952cb26ea9d2bab619bcb70e4305d33a98b96fdbf95ea33",
}


def _voice(name, seconds=6.0):
    import soundfile as sf
    x, fs = sf.read(os.path.join(ROOT, "docs", "samples", name + "__original.flac"))
    assert fs == 8000
    return np.round(x[:int(seconds * 8000)] * 32767).astype(np.int16)


def _slim(x16, tmp_path, *flags):
    x16.astype("<i2").tofile(tmp_path / "in.raw")
    subprocess.run([SLIM, *flags, str(tmp_path / "in.raw"), str(tmp_path / "out.bit")], check=True)
    return np.fromfile(tmp_path / "out.bit", np.uint8).reshape(-1, 6)


def _pesq(x16, bits):
    import audio_race as ar
    import check_fx
    y = check_fx.run_dec(DEC, np.unpackbits(bits, axis=1), lr=True)
    return ar.score(x16 / 32768.0, y, ar.CODEC_DELAY)[0]


@need
@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_slim_superframes_are_golden(name, tmp_path):
    b = _slim(_voice(name), tmp_path)
    assert len(b) == 150                                     # 6 s, the flush included
    assert hashlib.sha256(b.tobytes()).hexdigest() == GOLDEN[name]


@need
def test_slim_is_near_the_full_encoder(tmp_path):
    """PESQ-NB through the fixed-point sotto 1200 decoder: the two voices' mean within 0.3 of
    the full encoder's and neither more than 0.45 below (docs/sotto-slim.md: 0.08 below over
    35 voices; the female voice here, creaky over mains hum, is one of its hardest)."""
    import check_fx
    d = []
    for name in sorted(GOLDEN):
        x16 = _voice(name)
        full = np.packbits(check_fx.run_enc(FULL, x16, lr=True).astype(np.uint8), axis=1)
        slim = _slim(x16, tmp_path)
        assert len(slim) == len(full)
        d.append(_pesq(x16, slim) - _pesq(x16, full))
    assert min(d) > -0.45
    assert np.mean(d) > -0.3


@need
def test_slim_parts_swap_with_the_full_encoder(tmp_path):
    """The bench driver's -a full / -c full put the full encoder's analysis or coder in the
    slim one's place: each mix is a valid stream of the same length."""
    x16 = _voice("male_libri3436_15s", 3.0)
    n = len(_slim(x16, tmp_path))
    for flags in (("-a", "full"), ("-c", "full"), ("-a", "full", "-c", "full")):
        b = _slim(x16, tmp_path, *flags)
        assert abs(len(b) - n) <= 1
        assert _pesq(x16, b) > 2.0


@need
def test_slim_silence_and_short_input(tmp_path):
    """Silence codes as silence (energy 0 in every frame), and an input shorter than a
    superframe still gives one."""
    b = _slim(np.zeros(8000, np.int16), tmp_path)
    bits = np.unpackbits(b, axis=1)
    assert len(b) == 25
    assert not bits[:, 9:14].any()                           # ea
    assert len(_slim(np.zeros(160, np.int16), tmp_path)) == 1
