"""Quick check of the watermark with no codec build: a synthetic vowel (a harmonic comb with a
gliding pitch and random harmonic phases) is marked with the ID frame using its known pitch,
sent through the FM repeater simulation, read back with the same pitch track, and decoded.
Needs only numpy and scipy. python watermark/selftest.py
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harmonic as hm, fmchan as fc, fec


def vowel(seconds=8.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * hm.FS)
    t = np.arange(n) / hm.FS
    f0 = 120 + 15 * np.sin(2 * np.pi * 0.3 * t)
    phi = 2 * np.pi * np.cumsum(f0) / hm.FS
    x = np.zeros(n)
    for k in range(1, 30):
        fk = k * f0
        amp = np.exp(-((fk - 700) / 500) ** 2) + 0.5 * np.exp(-((fk - 1500) / 400) ** 2) + 0.05
        x += amp / k ** 0.5 * np.cos(k * phi + rng.uniform(0, 2 * np.pi)) * (fk < 3800)
    x *= 0.05 / np.sqrt(np.mean(x ** 2))
    return x, (f0, np.ones(n, bool))


def main():
    x, track = vowel()
    p = hm.Params()
    code = fec.Code(nsub=p.nsub)
    y, info = hm.embed(x, code.bits_for_slot, p, track)
    assert info["slots"].mean() > 0.9
    z, _ = fc.channel(y, "repeater", cnr_in=25, cnr_out=25)
    R, est = hm.Receiver(z, p, track).read()
    got = code.decode(R)
    print("decoded", got, "timing", est["offset"])
    assert got is not None and got[:2] == ("AG7EW", 0x5A), got
    zc, _ = fc.channel(x, "repeater", cnr_in=25, cnr_out=25)
    Rc, _ = hm.Receiver(zc, p, track).read()
    assert code.decode(Rc) is None, "unmarked audio decoded"
    print("ok")


if __name__ == "__main__":
    main()
