"""Where does Codec 2 2400 lose quality? Run each clip through c2sim with one more
simplification at each rung, from the unquantized sinusoidal model down to the full 2400
codec, and score each rung with PESQ / ESTOI.

Usage: python sim/oracle_ladder.py [--samples DIR] [--out FILE]
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio_race as ar

RUNGS = [
    ("model, true phases", []),
    ("+ synthetic phase (voicing)", ["--phase0"]),
    ("+ postfilter", ["--phase0", "--postfilter"]),
    ("+ LPC-10 envelope", ["--phase0", "--postfilter", "--lpc", "10"]),
    ("+ scalar LSP quant", ["--phase0", "--postfilter", "--lpc", "10", "--lsp"]),
    ("+ 2400 pitch/energy quant, 20 ms", ["--rate", "2400"]),
]


def c2sim(x, args):
    with tempfile.TemporaryDirectory() as d:
        np.round(x * 32767).astype("<i2").tofile(f"{d}/in.raw")
        subprocess.run([f"{ar.C2BIN}/c2sim", f"{d}/in.raw", "-o", f"{d}/out.raw"] + args,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


def main(samples, out):
    res = {}
    clips = ar.load_clips(samples)
    for c, x in clips.items():
        res[c] = {}
        for name, args in RUNGS:
            y = c2sim(x, args)
            p, e = ar.score(x, y, ar.best_lag(x, y))
            res[c][name] = (p, e)
        y = ar.c2dec(ar.c2enc(np.round(x * 32767)))
        res[c]["c2enc/c2dec 2400"] = ar.score(x, y, ar.best_lag(x, y))
    names = list(next(iter(res.values())).keys())
    print(f"{'rung':36s}" + "".join(f"{c[:18]:>20s}" for c in clips))
    for n in names:
        print(f"{n:36s}" + "".join(f"{res[c][n][0]:12.2f} ({res[c][n][1]:.2f})" for c in clips))
    if out:
        with open(out, "w") as f:
            json.dump(res, f, indent=1)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--samples", default=ar.SAMPLES)
    a.add_argument("--out")
    a = a.parse_args()
    main(a.samples, a.out)
