"""Render the listening set: for each clip, the original and the marked speech (full band and
narrow band), and both again as a listener hears them through a strong repeater (same noise
in both, so only the watermark differs). Every marked file is decoded before it is written,
and every unmarked one must not decode, so a mixed-up file can't reach the page.

python watermark/listen.py OUTDIR CLIP.flac [CLIP.flac ...]
"""
import os, sys
import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harmonic as hm, fmchan as fc, fec

VARIANTS = {
    "marked": dict(band=(500.0, 2600.0), nsub=4),
    "narrow": dict(band=(900.0, 2000.0), nsub=2),
}
REPEATER = dict(kind="repeater", cnr_in=40, cnr_out=40)


def decodes(z, p, code):
    R, _ = hm.Receiver(z, p).read()
    got = code.decode(R)
    return got is not None and got[:2] == ("AG7EW", 0x5A)


def raw_ber(z, p, code, used):
    """Share of marked slot bits read wrong (about 0.5 for audio that isn't marked)."""
    R, _ = hm.Receiver(z, p).read()
    n = min(len(R), len(used))
    ok = (np.abs(R[:n]).sum(1) > 0) & used[:n]
    bits = np.array([code.bits_for_slot(j) for j in range(n)])
    return float(np.mean((R[:n][ok] < 0) != bits[ok].astype(bool)))


def write(path, z):
    sf.write(path, np.clip(z, -1, 1), hm.FS, subtype="PCM_16")


def main():
    out, clips = sys.argv[1], sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    for clip in clips:
        name = os.path.basename(clip).split(".")[0]
        x, fs = sf.read(clip)
        assert fs == hm.FS
        track = hm.tx_track(x)
        write(f"{out}/{name}-clean.wav", x)
        zc, _ = fc.channel(x, **REPEATER)
        write(f"{out}/{name}-clean-rpt.wav", zc)
        for var, kw in VARIANTS.items():
            p = hm.Params(**kw)
            code = fec.Code(nsub=p.nsub)
            y, info = hm.embed(x, code.bits_for_slot, p, track)
            bm, bc = raw_ber(y, p, code, info["slots"]), raw_ber(x, p, code, info["slots"])
            print(name, var, f"raw bit errors marked {bm:.3f} clean {bc:.3f}", flush=True)
            assert bm < 0.15 and bc > 0.35, (name, var, bm, bc)
            assert not decodes(x, p, code), (name, var, "clean decoded")
            write(f"{out}/{name}-{var}.wav", y)
            if var == "marked":
                z, _ = fc.channel(y, **REPEATER)
                assert decodes(z, p, code), (name, var, "repeater")
                assert not decodes(zc, p, code), (name, var, "clean repeater decoded")
                write(f"{out}/{name}-{var}-rpt.wav", z)
            print(name, var, "ok", flush=True)


if __name__ == "__main__":
    main()
