"""Envelope training sequences: every 10 ms mean-removed rate-K shape (and frame energy) of
each training speaker, in time order, analysed with sotto v3.7's tracker (the one v3.8's
encoder runs). Unlike tools/sc_corpus.py, nothing is dropped, so interframe statistics
(prediction, interpolation-aware training) can be learnt from it.

Usage:
  python tools/env_corpus.py sc SC_DIR OUT.npz [--speakers 1200] [--max-seconds 8]
  python tools/env_corpus.py librispeech LS_DIR OUT.npz [--seconds 240]

sc: Google Speech Commands v0.02 (CC BY 4.0), words joined per speaker as in sc_corpus.py;
  --exclude samples-sc/clips.json keeps the 12 SC test speakers out.
librispeech: dev-clean (CC BY 4.0); the 8 speakers clean_corpus.py holds out for the test
set are skipped.
OUT.npz: shapes (N, 20) float16, energy (N,) float16 (dB, the v3.6 energy field's measure),
seg (N,) int32 segment index (frames are consecutive within a segment).
"""
import argparse, os, sys
from multiprocessing import Pool
import numpy as np, soundfile as sf
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))
sys.path.insert(0, HERE)
import vocoder_lab as vl                                       # noqa: E402

HELD_OUT = {"2428", "251", "3081", "3536", "6313", "652", "777", "8842"}


def analyse(x):
    if x is None or len(x) < 1600:
        return None
    m = vl.analyse(x, "tracked4")
    if len(m) % 2:
        m = np.concatenate([m, m[-1:]])
    rk = vl.to_rate_k(m)
    en = vl.frame_energy_db(vl.from_rate_k(m, rk))
    return (rk - rk.mean(1, keepdims=True)).astype(np.float16), en.astype(np.float16)


def ls_clip(args):
    files, seconds = args
    parts, n = [], 0
    for f in files:
        x, fs = sf.read(f)
        parts.append(resample_poly(x, 1, 2))
        n += len(parts[-1])
        if n > seconds * 8000:
            break
    x = np.concatenate(parts)
    return 0.5 * x / np.abs(x).max()


def main():
    a = argparse.ArgumentParser()
    a.add_argument("kind", choices=["sc", "librispeech"])
    a.add_argument("src")
    a.add_argument("out")
    a.add_argument("--speakers", type=int, default=1200)
    a.add_argument("--max-seconds", type=float, default=8.0)
    a.add_argument("--seconds", type=float, default=240.0)
    a.add_argument("--exclude", help="sc: JSON list of test clips (samples-sc/clips.json) whose speakers to skip")
    a = a.parse_args()
    if a.kind == "sc":
        import sc_corpus as sc
        by = {}
        for w in sorted(os.listdir(a.src)):
            if not os.path.isdir(os.path.join(a.src, w)) or w.startswith("_"):
                continue
            for f in os.listdir(os.path.join(a.src, w)):
                by.setdefault(f.split("_")[0], []).append(f"{w}/{f}")
        ex = set()
        if a.exclude:
            import json
            ex = {c["speaker"] if isinstance(c, dict) else c for c in json.load(open(a.exclude))}
        spk = sorted((s for s in by if len(by[s]) >= 15 and s not in ex), key=lambda s: -len(by[s]))[:a.speakers]
        rng = np.random.default_rng(0)
        jobs = [(a.src, list(rng.permutation(by[s])), a.max_seconds) for s in spk]
        with Pool(4) as p:
            clips = p.map(sc.speaker_clip, jobs)
    else:
        import clean_corpus as cc
        spk = {s: v for s, v in cc.librispeech(a.src).items() if s not in HELD_OUT}
        with Pool(4) as p:
            clips = p.map(ls_clip, [(v[1], a.seconds) for v in spk.values()])
    with Pool(4) as p:
        res = p.map(analyse, clips)
    res = [r for r in res if r is not None]
    shapes = np.concatenate([r[0] for r in res])
    energy = np.concatenate([r[1] for r in res])
    seg = np.concatenate([np.full(len(r[0]), i, np.int32) for i, r in enumerate(res)])
    np.savez_compressed(a.out, shapes=shapes, energy=energy, seg=seg)
    print(len(res), "segments,", len(shapes), "10 ms frames ->", a.out, flush=True)


if __name__ == "__main__":
    main()
