"""Progressive sotto (sim/sotto_prog.py, docs/sotto-progressive.md): the scan order is a
permutation of the streamed bits, a complete block decodes exactly as the streamed decoder,
and a lost packet's fields land spread over the block. Python only. SPDX-License-Identifier: MIT"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
import sotto_prog as sp  # noqa: E402

MODES = ("2400", "1200", "600", "400")


def random_superframes(n, seed=1):
    rng = np.random.default_rng(seed)
    b = rng.integers(0, 2, (n, 48)).astype(np.int8)
    b[rng.random(n) < 0.15, 9:14] = 0
    return b


@pytest.mark.parametrize("mode", MODES)
def test_scripts_cover_every_field_once(mode):
    for name, script in sp.SCRIPTS[mode].items():
        assert sp.check_script(mode, script), name


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("ns", [1, 2, 7, 64, 161])
def test_round_trip(mode, ns):
    b = random_superframes(ns)
    for script in sp.SCRIPTS[mode].values():
        pb = sp.to_progressive(mode, b, script)
        assert len(pb) == ns * 48
        back, known = sp.from_progressive(mode, pb, ns, script)
        assert np.array_equal(back, b)
        assert all(v.all() for v in known.values())


@pytest.mark.parametrize("mode", MODES)
def test_complete_block_decodes_as_streamed(mode):
    """Every field known: the partial decoder's model is the streamed decoder's, sample for
    sample (the full decode stays bit-exact, so the C ports need no change)."""
    b = random_superframes(40, seed=3)
    v = sp.codec(mode)
    want = v.decode(b)
    known = sp.known_after(mode, len(b), sp.SCRIPTS[mode]["SI"], 99)
    got = sp.synth()._synth(sp.partial_frames(mode, b, known))
    assert len(got) == len(want)
    for f in ("Wo", "L", "voiced"):
        assert np.array_equal(got[f], want[f]), f
    assert np.allclose(got["A"], want["A"], rtol=0, atol=1e-4)


def test_spread_order():
    """A permutation, and neighbouring superframes sit at least 0.3 n positions apart."""
    for n in range(1, 400):
        o = sp.spread_order(list(range(n)))
        assert sorted(o) == list(range(n))
        if n >= 8:
            pos = np.argsort(o)
            gap = np.abs(np.diff(pos))
            assert np.minimum(gap, n - gap).min() >= 0.3 * n, n


def test_lost_packet_is_spread():
    """One lost packet in a 160-superframe sotto 1200 block: in every scan that the packet
    covers less than 30% of, no two neighbouring superframes lose the same field, so each gap
    is filled from both sides."""
    b = random_superframes(160)
    for k in range(8):
        _, known = sp.lost_packets("1200", b, sp.SCRIPTS["1200"]["SI"], block=160,
                                   lost=lambda j, k=k: j == k)
        for f, kn in known.items():
            miss = np.where(~kn)[0]
            if len(miss) < 0.3 * 160 * (0.5 if f in ("ca", "wa", "ea", "sa0") else 1):
                assert not np.any(np.diff(miss) == 1), (k, f, miss)


def test_partial_decode_runs_on_every_prefix():
    b = random_superframes(30, seed=5)
    for mode in MODES:
        script = sp.SCRIPTS[mode]["SI"]
        for k in range(len(script) + 1):
            fp = sp.partial_frames(mode, b, sp.known_after(mode, len(b), script, k))
            assert len(fp) == len(b) * {"2400": 1, "1200": 2, "600": 4, "400": 6}[mode]


def test_prior_table():
    p = sp.load_prior()
    assert p.shape == (4, 19)
    assert np.abs(p).max() < 128          # fits int8 dB steps on a radio


@pytest.mark.parametrize("mode,ratio", [("2400", 1.65), ("2400", 1.24), ("1200", 0.85)])
def test_jit_order(mode, ratio):
    """The just-in-time order sends every field once, the base scan first, and every item it
    schedules before the late tail arrives before its superframe plays."""
    ns = 120
    script = sp.SCRIPTS[mode]["SI"]
    seq = sp.jit_order(mode, ns, script, 1, ratio)
    names = [k for k, w in sp.layout(mode) if w]
    assert sorted(seq) == sorted((s, k) for s in range(ns) for k in names)
    base, _ = sp.order(mode, ns, script)
    nb = len(range(0, ns, 2)) * len(script[0][0])
    assert seq[:nb] == base[:nb]
    w = dict(sp.layout(mode))
    cum = np.cumsum([w[k] for _, k in seq])
    base_bits = cum[nb - 1]
    last = -1
    for i in range(nb, len(seq)):
        s = seq[i][0]
        if s < last:                 # the late tail starts where time order breaks
            break
        last = s
        assert cum[i] <= base_bits + s * 48 / ratio + 1e-9


@pytest.mark.parametrize("mode", ["2400", "1200"])
def test_hiss_complete_block_decodes_as_streamed(mode):
    """With the 4-8 kHz hiss band too, a complete block's 16 kHz output is the streamed
    decoder's (v3.8, sotto 1200 hiss), sample for sample."""
    b = random_superframes(60, seed=7)
    n16 = 60 * 320 * (2 if mode == "1200" else 1)
    want = sp.decode16(mode, b, n16=n16)
    got = sp.decode16(mode, b, sp.known_after(mode, len(b), sp.SCRIPTS[mode]["SI"], 99), n16=n16)
    assert np.array_equal(want, got)


def test_hiss_fill_copies_the_nearest_uu_index():
    code = np.array([0, 0, 1, 0, 0])
    wi = np.array([10, 99, 60, 99, 40])
    have = np.array([True, False, True, False, True])
    c, w, _ = sp._fill_vpe(code, wi, np.zeros(5, int), have, hiss=True)
    assert c[1] == 0 and w[1] == 10            # UU: the nearest UU frame's index, copied
    assert c[3] == 1 and w[3] == 60            # voiced (nearer neighbour wins a tie by coming first): its pitch
