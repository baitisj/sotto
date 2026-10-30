"""Softmodem tests: framing primitives, payload codes, and the full audio path under the
impairments a sound card, a radio's data port or an SDR put on the signal.

Run: python -m pytest tests
"""
import os
import sys

import numpy as np
import pytest
from scipy import signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sim"))

from modem import fec, payload, sdr, ysf                     # noqa: E402
from modem.link import Transmitter, Receiver                  # noqa: E402
from modem.__main__ import main as cli                        # noqa: E402
import waveforms as wf                                        # noqa: E402

RNG = np.random.default_rng(7)
CODEC = RNG.integers(0, 2, (100, 48)).astype(np.int8)        # 2 s of 2400 bit/s frames
LEAD = 2400 + 4800                                             # modulator lead-in + header frame


def _tx(scheme="sotto_vw", pad=7777):
    f = Transmitter(scheme).modulate(CODEC)
    return np.concatenate([np.zeros(pad), f, np.zeros(3000)]), pad + LEAD


def _fer(x, t0, fs=48000, scheme="sotto_vw"):
    out = Receiver(scheme, fs=fs).receive(x, conceal=False, t0=t0)
    fr = out["raw_frames"]
    n = min(len(fr), len(CODEC))
    if n < len(CODEC):
        return 1.0, out
    return float((fr[:n] != CODEC[:n]).any(1).mean()), out


# ------------------------------------------------------------- framing primitives
def test_golay_matches_reference_table():
    # first entries of the Golay(24,12) table used by existing YSF implementations
    ref = [0x000000, 0x0018EB, 0x00293E, 0x0031D5, 0x004A97, 0x00527C, 0x0063A9, 0x007B42]
    assert [ysf.golay24_encode(d) for d in range(8)] == ref


def test_golay_corrects_three_errors():
    for d in RNG.integers(0, 4096, 200):
        c = ysf.golay24_encode(int(d))
        e = sum(1 << int(p) for p in RNG.choice(24, 3, replace=False))
        assert ysf.golay24_decode(c ^ e) == (d, True)


def test_crc16_check_value():
    assert ysf.crc16(b"123456789") == 0x31C3 ^ 0xFFFF      # CRC-16/XMODEM, inverted


def test_fich_roundtrip_with_errors():
    f = ysf.FICH(fi=ysf.FI_COMMS, fn=4, ft=6, dt=ysf.DT_VOICE_FR, dgid=33, sotto=True)
    llr = 1.0 - 2.0 * f.encode()
    assert ysf.FICH.decode(llr) == f
    llr[::15] *= -1                                          # 14 of 200 bits wrong
    assert ysf.FICH.decode(llr) == f
    assert ysf.FICH.decode(RNG.standard_normal(200)) is None


def test_header_callsigns():
    p = ysf.header_payload("CQCQCQ", "W1AW")
    h = ysf.decode_header_payload(1.0 - 2.0 * p)
    assert (h["dest"], h["src"]) == ("CQCQCQ", "W1AW")


def test_tail_biting_code():
    u = RNG.integers(0, 2, 240).astype(np.int8)
    c = fec.encode(u)
    llr = (1.0 - 2.0 * c) * 2
    llr[RNG.choice(240, 20, replace=False), 0] *= -1
    assert (fec.decode(llr) == u).all()


@pytest.mark.parametrize("name", sorted(payload.SCHEMES))
def test_payload_roundtrip(name):
    s = payload.SCHEMES[name]
    fr = RNG.integers(0, 2, (5, 48)).astype(np.int8)
    p = s.encode(fr)
    assert len(p) == ysf.PAYLOAD_BITS
    bits, good, _ = s.decode(1.0 - 2.0 * p)
    assert (bits == fr).all() and good.all()


def test_crc_flags_garbage():
    s = payload.SCHEMES["sotto_vw"]
    _, good, _ = s.decode(RNG.standard_normal(720))
    assert not good.any()


# ------------------------------------------------------------- full audio path
def test_loopback_bit_exact():
    x, t0 = _tx()
    fer, out = _fer(x, t0)
    assert fer == 0.0
    assert out["header"]["src"] == "N0CALL"


@pytest.mark.parametrize("name", sorted(payload.SCHEMES))
def test_loopback_all_schemes(name):
    x, t0 = _tx(name)
    assert _fer(x, t0, scheme=name)[0] == 0.0


def _soundcard(x):
    d, _ = wf.fm_channel(x, 62, seed=3)                     # a strong signal, then the sound card:
    return -0.21 * d / 1800 + 0.05                          # inverted, quiet, DC offset


@pytest.mark.parametrize("case", ["level_polarity_dc", "ac_coupled_30hz", "44k1_plus_100ppm",
                                  "48k_minus_200ppm"])
def test_soundcard_impairments(case):
    x, t0 = _tx()
    y = _soundcard(x)
    fs = 48000
    if case == "ac_coupled_30hz":
        b, a = signal.butter(1, 30, "high", fs=48000)
        y = signal.lfilter(b, a, y)
    elif case == "44k1_plus_100ppm":
        y, fs = signal.resample_poly(y, 1470147, 1600000), 44100
    elif case == "48k_minus_200ppm":
        y = signal.resample_poly(y, 9998, 10000)
    assert _fer(y, t0, fs)[0] == 0.0


def test_noisy_fm_channel():
    x, t0 = _tx()
    d, _ = wf.fm_channel(x, 50, seed=11)                   # ~1% raw BER
    assert _fer(d, t0)[0] < 0.02


def test_fading_channel_conceals():
    x, t0 = _tx()
    d, _ = wf.fm_channel(x, 52, fd=25.0, seed=5)            # 446 MHz at 60 km/h
    fer, out = _fer(d, t0)
    assert fer < 0.1
    bad = (out["raw_frames"][:100] != CODEC).any(1)
    assert (~out["good"][:100] >= bad).all()               # every wrong frame is flagged


def test_iq_path():
    f = Transmitter().modulate(CODEC)
    iq = sdr.fm_modulate(f, 48000, 240000)
    rng = np.random.default_rng(1)
    iq = iq * np.exp(1j * 2 * np.pi * 300 * np.arange(len(iq)) / 240000)    # 300 Hz mistuning
    iq = iq + 0.05 * (rng.standard_normal(len(iq)) + 1j * rng.standard_normal(len(iq)))
    d = sdr.fm_demodulate(iq.astype(np.complex64), 240000)
    assert _fer(d, LEAD)[0] == 0.0


def test_cli_roundtrip(tmp_path):
    bit = tmp_path / "v.bit"
    np.packbits(CODEC.astype(np.uint8).reshape(-1)).tofile(bit)
    wav, back = tmp_path / "v.wav", tmp_path / "back.bit"
    assert cli(["tx", str(bit), str(wav), "--rate", "44100", "--src", "K1ABC"]) == 0
    assert cli(["rx", str(wav), str(back)]) == 0
    got = np.unpackbits(np.fromfile(back, np.uint8)).reshape(-1, 48)
    assert (got[:100] == CODEC).all()
