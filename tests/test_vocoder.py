"""Vocoder lab tests: the Python sinusoidal analysis must match c2sim, the pitch tracker must
undo octave errors, and the sotto encoders must produce 48-bit frames that decode.

Needs the Codec 2 tools (tools/build_codec2.sh); skipped without them.
Run: python -m pytest tests
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))

import audio_race as ar                                       # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(ar.C2BIN, "c2sim")),
                                reason="Codec 2 tools not built")

import vocoder_lab as vl                                      # noqa: E402
import sinusoid as sn                                         # noqa: E402

FS = 8000


def _vowel(f0, seconds=1.0, formants=(700, 1200, 2600)):
    """Glottal-ish pulse train at f0 through three formant resonators, plus a little noise."""
    from scipy import signal
    n = int(seconds * FS)
    x = np.zeros(n)
    x[(np.arange(0, n, FS / f0)).astype(int)] = 1.0
    for f in formants:
        r = np.exp(-np.pi * 80 / FS)
        x = signal.lfilter([1], [1, -2 * r * np.cos(2 * np.pi * f / FS), r * r], x)
    x += 1e-3 * np.random.default_rng(1).standard_normal(n)
    return 0.3 * x / np.abs(x).max()


def _ve9qrp(seconds=3.0):
    raw = os.path.join(ROOT, "codec", "codec2", "raw", "ve9qrp_10s.raw")
    return np.fromfile(raw, "<i2")[:int(seconds * FS)].astype(float) / 32768


def test_analysis_matches_c2sim():
    x = _ve9qrp()
    m = vl.analyse(x)
    mine = sn.analyse(np.round(x * 32767), m["Wo"], do_refine=False)
    assert len(mine) == len(m)
    for r, q in zip(m, mine):
        L = r["L"]
        assert q["L"] == L
        np.testing.assert_allclose(q["A"][1:L + 1], r["A"][1:L + 1], rtol=1e-3, atol=1e-2)
    assert np.mean(mine["voiced"] == m["voiced"]) > 0.99      # float rounding at the 6 dB edge


def test_tracker_undoes_doubled_pitch():
    x = _vowel(180)
    Sw = sn.spectra(np.round(x * 32767))
    wo_true = 2 * np.pi * 180 / FS
    doubled = np.full(len(Sw), 2 * wo_true)
    doubled[::3] = wo_true                       # an octave error on two frames in three
    wo = sn.track_pitch(Sw, doubled, np.ones(len(Sw), int))
    mid = slice(5, -5)
    assert np.all(np.abs(np.log(wo[mid] / wo_true)) < 0.05)


def test_tracker_keeps_low_male_pitch():
    x = _vowel(95)
    Sw = sn.spectra(np.round(x * 32767))
    wo_true = 2 * np.pi * 95 / FS
    wo = sn.track_pitch(Sw, np.full(len(Sw), wo_true), np.ones(len(Sw), int))
    assert np.all(np.abs(np.log(wo[5:-5] / wo_true)) < 0.05)   # no halving below 70 Hz


@pytest.mark.parametrize("pitch", ["c2", "tracked"])
def test_codec_frames_decode(pitch):
    x = _ve9qrp(2.0)
    v = vl.SottoV0(pitch=pitch)
    bits = v.encode(x)
    assert bits.shape == (len(x) // 160, 48) and set(np.unique(bits)) <= {0, 1}
    y = v.decode_audio(bits)
    lag = ar.best_lag(x, y)
    pesq, _ = ar.score(x, y, lag)
    assert pesq > 2.2


def test_joint_tracker_follows_pitch_above_400_hz():
    x = _vowel(440, formants=(800, 1500, 2800))
    Sw = sn.spectra(np.round(x * 32767))
    wo_c2 = np.full(len(Sw), sn.WO_MAX)              # Codec 2 clamps at 400 Hz
    wo, v = sn.track_pitch_voicing(Sw, wo_c2, np.ones(len(Sw), int))
    mid = slice(5, -5)
    assert np.all(v[mid] == 1)
    assert np.all(np.abs(np.log(wo[mid] / (2 * np.pi * 440 / FS))) < 0.05)


def test_joint_tracker_unvoices_noise():
    x = 0.1 * np.random.default_rng(3).standard_normal(FS)
    m = vl.analyse(x)                                 # Codec 2 calls some of it voiced
    Sw = sn.spectra(np.round(x * 32767))
    _, v = sn.track_pitch_voicing(Sw, m["Wo"], m["voiced"])
    assert v.mean() <= m["voiced"].mean() and v.mean() < 0.05


def test_v3_frames_decode():
    x = _ve9qrp(2.0)
    v = vl.SottoV3()
    bits = v.encode(x)
    assert bits.shape == (len(x) // 160, 48)
    pesq, _ = ar.score(x, v.decode_audio(bits), ar.best_lag(x, None))
    assert pesq > 2.5
    idx = v.vq.indices(np.zeros((1, vl.K)))
    assert idx.shape == (1, 3)


def test_v31_only_unvoices_quiet_tails():
    x = _ve9qrp(4.0)
    m3 = vl.analyse(x, "tracked2")
    m31 = vl.analyse(x, "tracked2t")
    gone = (m3["voiced"] > 0) & (m31["voiced"] == 0)
    assert not ((m31["voiced"] > 0) & (m3["voiced"] == 0)).any()
    e = vl.frame_energy_db(m3)
    for k in np.where(gone)[0]:
        assert e[k] < e[max(0, k - 30):k + 1].max() - 20
    bits = vl.SottoV31().encode(x)
    assert bits.shape == (len(x) // 160, 48)
