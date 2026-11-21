#!/usr/bin/env python3
"""Compare the C synthesiser (c/tts/sotto_tts) with the Python prototype (tts/synth.py).

    make -C c/tts && python tools/tts_ccheck.py [--robot]

Per sentence: the phones must match, and per 20 ms frame the voicing code, pitch index and
energy code; the shape coefficients within 0.01 dB (C reads the K6's fixed-point codebook) (the largest difference is printed). The
superframes differ where the fixed-point coder (C) and the float one (Python) choose
differently between near-equal shapes; their count is printed.
SPDX-License-Identifier: MIT
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]

SENTENCES = [
    "This is AG7EW on 440.850 MHz.",
    "Is the repeater on, please?",
    "The quick brown fox jumps over the lazy dog!",
    "Meet me at 1950 hours; bring 12 batteries and the 5W radio.",
    "KD7ABC/P calling CQ, over.",
    "The birch canoe slid on the smooth planks.",
    "Glue the sheet to the dark blue background.",
    "It's easy to tell the depth of a well.",
    "Message received from AG7EW at 9.30 UTC.",
    "Antennas, feedlines and well-made connectors matter more than power.",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", action="store_true")
    ap.add_argument("--exe", default=os.path.join(ROOT, "c", "tts", "sotto_tts"))
    a = ap.parse_args()
    from tts import synth
    tab = synth.load_table(os.path.join(ROOT, "tts", "data", "robot.stt" if a.robot else "diphone.stt"))
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        for s in SENTENCES:
            pp, sot = os.path.join(d, "p.txt"), os.path.join(d, "o.sot")
            subprocess.run([a.exe] + (["-robot"] if a.robot else []) + ["-params", pp, s, sot],
                           check=True, capture_output=True)
            lines = open(pp).read().splitlines()
            cph = lines[0]
            M = np.array([[float(v) for v in l.split()] for l in lines[1:]])
            p, rep = synth.synth_params(s, tab)
            ok_ph = cph == rep["phones"]
            n = min(len(M), len(p["code"]))
            same_len = len(M) == len(p["code"])
            dc = int((M[:n, 0] != p["code"][:n]).sum())
            dw = int((M[:n, 1] != p["wi"][:n]).sum())
            de = int((M[:n, 2] != p["ei"][:n]).sum())
            import vocoder_lab as vl
            cpy = (p["shape"] @ vl.DCT.T)[:, 1:]
            dsh = float(np.abs(M[:n, 3:] - cpy[:n]).max())
            bc = np.unpackbits(np.fromfile(sot, np.uint8)).reshape(-1, 48)
            bp = np.asarray(synth.encode(p), np.uint8).reshape(-1, 48)
            m = min(len(bc), len(bp))
            dsf = int((bc[:m] != bp[:m]).any(1).sum())
            fail = not (ok_ph and same_len and dc == 0 and de == 0 and dw <= 1 and dsh < 0.01)
            bad += fail
            print(f"{'FAIL' if fail else 'ok  '} frames {len(M)}/{len(p['code'])} phones {'=' if ok_ph else '!='} "
                  f"code {dc} wi {dw} ei {de} shape {dsh:.1e} superframes differ {dsf}/{m}: {s}")
            if not ok_ph:
                print("   C :", cph)
                print("   py:", rep["phones"])
    print("all match" if not bad else f"{bad} sentences differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
