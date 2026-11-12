"""The fixed-point sotto 1200 encoders (c/fixed/sotto_fx_lr_enc.c) against the float ones
(c/sotto_lr.c, c/sotto_hiss.c): most superframes give the same 48 bits, the float decoder gets
the same PESQ from them, and the Cortex-M4 and Cortex-M0 code paths give the same bits as the
default build. Needs make -C c all fixed (tools/build_codec2.sh first); the 16 kHz tests need
the default VARIANT=v3.8 build. SPDX-License-Identifier: MIT"""
import os
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

C = os.path.join(ROOT, "c")
FX = os.path.join(C, "fixed")


def _works(exe, *flags):
    if not os.path.exists(exe):
        return False
    return subprocess.run([exe, *flags, "/dev/null", "/dev/null"], capture_output=True).returncode == 0


need_lr = pytest.mark.skipif(not (_works(os.path.join(C, "sotto_enc"), "-1200")
                                  and _works(os.path.join(FX, "sotto_enc_fx"), "-1200")),
                             reason="needs make -C c all fixed")


def _ve9qrp(seconds):
    raw = os.path.join(ROOT, "codec", "codec2", "raw", "ve9qrp_10s.raw")
    return np.fromfile(raw, "<i2")[:int(seconds * 8000)]


def _score(ref, out):
    import audio_race as ar
    return ar.score(ref, out, ar.CODEC_DELAY)[0]


@need_lr
def test_fixed_lr_encoder_matches_float():
    import check_fx
    x16 = _ve9qrp(6.0)
    bf = check_fx.run_enc(os.path.join(C, "sotto_enc"), x16, lr=True)
    bx = check_fx.run_enc(os.path.join(FX, "sotto_enc_fx"), x16, lr=True)
    assert bx.shape == bf.shape
    assert np.mean(np.all(bf == bx, 1)) > 0.85
    x = x16 / 32768.0
    for good in (None, np.arange(len(bf)) % 8 != 3):
        pf = _score(x, check_fx.run_dec(os.path.join(C, "sotto_dec"), bf, good, lr=True))
        px = _score(x, check_fx.run_dec(os.path.join(C, "sotto_dec"), bx, good, lr=True))
        assert px > pf - 0.1


@need_lr
@pytest.mark.parametrize("variant", ["arm", "m0"])
def test_fixed_lr_encoder_code_paths_are_bit_exact(variant):
    """FX_ARM_DSP (SMLAD codebook search, emulated on x86) and FX_NARROW_MUL give the default
    build's superframes, a tail that is not a whole superframe included."""
    import check_fx
    exe = os.path.join(FX, f"sotto_enc_fx_{variant}")
    if not os.path.exists(exe):
        pytest.skip(f"{exe} not built")
    x16 = _ve9qrp(3.0)[:3 * 8000 - 240]
    b = check_fx.run_enc(os.path.join(FX, "sotto_enc_fx"), x16, lr=True)
    assert np.array_equal(b, check_fx.run_enc(exe, x16, lr=True))


# ---- 16 kHz: sotto 1200 hiss (VARIANT=v3.8) ----
need_lr16 = pytest.mark.skipif(not (_works(os.path.join(C, "sotto_enc"), "-16", "-1200")
                                    and _works(os.path.join(FX, "sotto_enc_fx"), "-16", "-1200")
                                    and _works(os.path.join(FX, "sotto_dec_fx"), "-16", "-1200")),
                               reason="needs the VARIANT=v3.8 build (make -C c all fixed)")


def _speech16(seconds):
    """ve9qrp at 16 kHz with hiss above 4.5 kHz, as tests/test_vocoder.py's ARM check"""
    from scipy import signal
    x = _ve9qrp(seconds).astype(float)
    hiss = signal.sosfilt(signal.butter(6, 4500, "highpass", fs=16000, output="sos"),
                          np.random.default_rng(1).standard_normal(2 * len(x)))
    y = signal.resample_poly(x, 2, 1) + 1500 * hiss
    return np.clip(y, -32767, 32767).astype(np.int16)[:len(y) // 640 * 640]


@need_lr16
def test_fixed_lr16_encoder_matches_float():
    import check_fx
    from scipy.signal import resample_poly
    x16 = _speech16(6.0)
    bf = check_fx.run_enc(os.path.join(C, "sotto_enc"), x16, k16=True, lr=True)
    bx = check_fx.run_enc(os.path.join(FX, "sotto_enc_fx"), x16, k16=True, lr=True)
    assert bx.shape == bf.shape
    assert np.mean(np.all(bf == bx, 1)) > 0.8
    x8 = resample_poly(x16 / 32768.0, 1, 2)
    pf = _score(x8, resample_poly(check_fx.run_dec(os.path.join(C, "sotto_dec"), bf, k16=True, lr=True), 1, 2))
    px = _score(x8, resample_poly(check_fx.run_dec(os.path.join(C, "sotto_dec"), bx, k16=True, lr=True), 1, 2))
    assert px > pf - 0.15


@need_lr16
def test_fixed_lr16_decoder_follows_float():
    """The full v3.8 layer on the fixed sotto 1200 decoder, against the float one on the same
    bits with losses: the same length, the 4-8 kHz band at the same level (its noise has
    random phase, so levels, not samples) and the same PESQ."""
    import check_fx
    import hiss_band as hb
    from scipy.signal import resample_poly
    x16 = _speech16(4.0)
    b = check_fx.run_enc(os.path.join(C, "sotto_enc"), x16, k16=True, lr=True)
    good = np.arange(len(b)) % 8 != 3
    yf = check_fx.run_dec(os.path.join(C, "sotto_dec"), b, good, k16=True, lr=True)
    yx = check_fx.run_dec(os.path.join(FX, "sotto_dec_fx"), b, good, k16=True, lr=True)
    assert len(yx) == len(yf)
    hf = hb.bands_db(np.abs(hb.stft(yf)) ** 2, [(4000, 8000)])[:, 0]
    hx = hb.bands_db(np.abs(hb.stft(yx)) ** 2, [(4000, 8000)])[:, 0]
    d = np.abs(hf - hx)[hf > -60]
    assert np.mean(d) < 1.5
    x8 = resample_poly(x16 / 32768.0, 1, 2)
    assert _score(x8, resample_poly(yx, 1, 2)) > _score(x8, resample_poly(yf, 1, 2)) - 0.15


@need_lr16
@pytest.mark.parametrize("variant", ["arm", "m0"])
def test_fixed_lr16_code_paths_are_bit_exact(variant):
    import check_fx
    enc, dec = os.path.join(FX, f"sotto_enc_fx_{variant}"), os.path.join(FX, f"sotto_dec_fx_{variant}")
    if not (os.path.exists(enc) and os.path.exists(dec)):
        pytest.skip(f"{variant} build missing")
    x16 = _speech16(3.0)
    b = check_fx.run_enc(os.path.join(FX, "sotto_enc_fx"), x16, k16=True, lr=True)
    assert np.array_equal(b, check_fx.run_enc(enc, x16, k16=True, lr=True))
    good = np.arange(len(b)) % 8 != 3
    assert np.array_equal(check_fx.run_dec(os.path.join(FX, "sotto_dec_fx"), b, good, k16=True, lr=True),
                          check_fx.run_dec(dec, b, good, k16=True, lr=True))


@need_lr
@pytest.mark.parametrize("dec", [os.path.join(C, "sotto_dec"), os.path.join(FX, "sotto_dec_fx")])
def test_good_2_keeps_the_last_good_shape(dec, tmp_path):
    """good = 2 (a link with unequal error protection): the superframe's voicing, pitch and
    energy are used, its shape fields (bits 14-31 and 40-47) are the last good superframe's.
    So garbled shapes under good = 2 decode exactly as the same superframes with the shapes
    copied forward by hand."""
    x = _ve9qrp(4)
    (tmp_path / "x.raw").write_bytes(x.astype("<i2").tobytes())
    subprocess.run([os.path.join(C, "sotto_enc"), "-1200", tmp_path / "x.raw", tmp_path / "x.bit"], check=True)
    b = np.unpackbits(np.frombuffer((tmp_path / "x.bit").read_bytes(), np.uint8)).reshape(-1, 48)
    shape = np.zeros(48, bool)
    shape[14:32] = shape[40:48] = True
    rng = np.random.default_rng(2)
    good = np.where(np.arange(len(b)) % 3 == 1, 2, 1).astype(np.uint8)
    good[7] = 0                                           # a lost one in between still conceals
    garbled, by_hand = b.copy(), b.copy()
    last = b[0]
    for i in range(len(b)):
        if good[i] == 2:
            garbled[i, shape] = rng.integers(0, 2, shape.sum())
            by_hand[i, shape] = last[shape]
        if good[i]:
            last = by_hand[i]

    def decode(bits, g):
        (tmp_path / "in.bit").write_bytes(np.packbits(bits.astype(np.uint8), axis=1).tobytes())
        (tmp_path / "g.u8").write_bytes(g.tobytes())
        subprocess.run([dec, "-1200", tmp_path / "in.bit", tmp_path / "y.raw", tmp_path / "g.u8"], check=True)
        return (tmp_path / "y.raw").read_bytes()

    y2 = decode(garbled, good)
    assert y2 == decode(by_hand, np.minimum(good, 1))
    assert y2 != decode(garbled, np.minimum(good, 1))     # the garbled shapes do matter
