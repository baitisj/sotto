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
