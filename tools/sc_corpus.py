"""Training shapes from Google Speech Commands v0.02 (CC BY 4.0, Warden 2018).

Download (2.3 GB):
  curl -O https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz
Usage: python tools/sc_corpus.py SC_DIR OUT.npz [--speakers 600] [--exclude FILE.json]

Each speaker's words are trimmed and joined into one clip at 8 kHz. Speakers are split by
median pitch (above/below 165 Hz) and taken equally from both halves, so higher voices are
not swamped. Each clip is analysed with sotto v2's tracker, and the mean-removed rate-K
shapes of the non-silent 20 ms frames are saved, with each frame's speaker index.
"""
import argparse, json, os, sys
from multiprocessing import Pool
import numpy as np, soundfile as sf
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))
import vocoder_lab as vl                                       # noqa: E402

WORDS = None


def trim(x, f=160):
    n = len(x) // f
    e = 10 * np.log10((x[:n * f].reshape(n, f) ** 2).mean(1) + 1e-10)
    on = np.where(e > np.percentile(e, 10) + 15)[0]
    if len(on) == 0 or np.abs(x).max() > 0.98:
        return None
    return x[max(0, on[0] - 4) * f:min(n, on[-1] + 5) * f]


def speaker_clip(args):
    d, files, max_s = args
    parts = []
    for f in files:
        x, fs = sf.read(os.path.join(d, f))
        y = trim(x)
        if y is not None:
            parts += [y, np.zeros(fs // 10)]
        if sum(map(len, parts)) > max_s * fs:
            break
    if len(parts) < 10:
        return None
    x = resample_poly(np.concatenate(parts), 1, 2)
    return 0.5 * x / np.abs(x).max()


def analyse(x):
    m = vl.analyse(x, "tracked2")
    v = m["voiced"] > 0
    f0 = float(np.median(m["Wo"][v]) * vl.FS / (2 * np.pi)) if v.sum() > 20 else 0.0
    rk = vl.to_rate_k(m)[::2]
    mean = rk.mean(1)
    live = mean > np.percentile(mean, 25)
    return f0, (rk - mean[:, None])[live].astype(np.float32)


def main(d, out, n_spk, exclude, max_s):
    ex = set(json.load(open(exclude))) if exclude else set()
    by = {}
    for w in sorted(os.listdir(d)):
        if not os.path.isdir(os.path.join(d, w)) or w.startswith("_"):
            continue
        for f in os.listdir(os.path.join(d, w)):
            s = f.split("_")[0]
            if s not in ex:
                by.setdefault(s, []).append(f"{w}/{f}")
    spk = sorted((s for s in by if len(by[s]) >= 15), key=lambda s: -len(by[s]))
    print(len(spk), "speakers with 15+ words", flush=True)
    rng = np.random.default_rng(0)
    cand = spk[:4 * n_spk]
    with Pool(4) as p:
        clips = p.map(speaker_clip, [(d, list(rng.permutation(by[s])), max_s) for s in cand])
        res = p.map(analyse, [c if c is not None else np.zeros(800) for c in clips])
    rows = [(s, f0, sh) for s, c, (f0, sh) in zip(cand, clips, res) if c is not None and f0 > 0]
    hi = [r for r in rows if r[1] >= 165][:n_spk // 2]
    lo = [r for r in rows if r[1] < 165][:n_spk - len(hi)]
    keep = hi + lo
    print(f"{len(rows)} analysed; keeping {len(hi)} higher and {len(lo)} lower voices", flush=True)
    shapes = np.concatenate([r[2] for r in keep])
    spk_idx = np.concatenate([np.full(len(r[2]), i) for i, r in enumerate(keep)])
    np.savez_compressed(out, shapes=shapes, speaker=spk_idx, names=[r[0] for r in keep],
                        f0=[r[1] for r in keep])
    print(shapes.shape, "frames saved to", out, flush=True)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("sc_dir")
    a.add_argument("out")
    a.add_argument("--speakers", type=int, default=600)
    a.add_argument("--exclude")
    a.add_argument("--max-seconds", type=float, default=8.0)
    a = a.parse_args()
    main(a.sc_dir, a.out, a.speakers, a.exclude, a.max_seconds)
