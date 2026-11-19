"""Envelope (shape) quantizer lab: run sotto v3.7's 8 kHz core (= v3.8's 0-4 kHz core) with
any shape quantizer swapped in, and score it on the held-out clean voices.

A quantizer is an object with reset() and quant(shape) -> decoded shape, where shape is one
mean-removed 20-point rate-K vector (dB) per 20 ms frame, called in time order (so
predictive quantizers can keep state). Everything else in the frame (voicing, pitch, energy,
postfilter, interpolation) is v3.7's.

Used as a library by the envelope-VQ experiments; `python tools/env_vq_lab.py` scores the
shipped 9+9+8+8 codebook and the unquantized-shape ceiling.
"""
import functools, hashlib, os, sys
from multiprocessing import Pool
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
import vocoder_lab as vl                                       # noqa: E402
import audio_race as ar                                        # noqa: E402
import hiss_band as hb                                         # noqa: E402
import sotto_lr_hiss as lh                                     # noqa: E402

WB = os.path.join(ROOT, "docs", "samples", "v38")
CLEAN = os.environ.get("SAMPLES_CLEAN", "/mnt/project-files/vocoder/samples-clean")

_analyse = vl.analyse
CACHE = os.environ.get("ENV_VQ_CACHE", "/tmp/env_vq_cache")   # analysis results, keyed by audio hash
_cache = {}


def _cached_analyse(x, pitch="c2"):
    key = (hashlib.sha1(np.ascontiguousarray(x).tobytes()).hexdigest(), pitch)
    if key not in _cache:
        f = os.path.join(CACHE, f"{key[0][:16]}_{pitch}.npy") if CACHE else None
        if f and os.path.exists(f):
            _cache[key] = np.load(f)
        else:
            _cache[key] = _analyse(x, pitch)
            if f:
                os.makedirs(CACHE, exist_ok=True)
                np.save(f, _cache[key])
    return _cache[key].copy()


vl.analyse = _cached_analyse


class Shipped:
    """v3.6-v3.8's shape quantizer: 9+9+8+8 MSVQ, int8 values, M-best 8. wpick / wsearch: see
    vocoder_lab.ShapeMSVQ (the plain search when both are None)."""

    def __init__(self, vq=None, path=None, wpick=None, wsearch=None):
        self.vq = vq or vl.round_codebook(vl.ShapeMSVQ.load(path or os.path.join(ROOT, "sim", "data", "shape_msvq_9988.npz")))
        self.vq.wpick, self.vq.wsearch = wpick, wsearch

    def reset(self):
        pass

    def quant(self, s):
        return self.vq.quantize(s[None])[0]


class Oracle:
    def reset(self):
        pass

    def quant(self, s):
        return s


class Lab(vl.SottoV37):
    """SottoV37 whose shape field is a side list filled by the quantizer `q`."""

    def __init__(self, q):
        self.q = q
        super().__init__()

    def encode(self, x):
        self.q.reset()
        self._prepare(x)
        self._hats, self._raw = [], []
        return super().encode(x)

    def _prepare(self, x8):
        """Sequence quantizers (q.prepare) see every 10 ms shape of the clip first."""
        if hasattr(self.q, "prepare"):
            self.q.prepare(shapes10(x8, self.PITCH))

    def _shape_idx(self, shape):
        self._raw.append(np.array(shape))
        self._hats.append(np.asarray(self.q.quant(np.asarray(shape, float)), float))
        return [0] * len(self.fields)

    def decode(self, bits, *a, **kw):
        self._k = 0
        return super().decode(bits, *a, **kw)

    def _shape_val(self, idx):
        h = self._hats[self._k]
        self._k += 1
        return h


class Lab38(Lab, hb.SottoV38):
    """v3.8 (candidate settings, 16 kHz in and out) with the shape quantizer swapped."""

    def __init__(self, q):
        self.q = q
        hb.SottoV38.__init__(self, **lh.V38)

    def encode(self, x16):
        from scipy.signal import resample_poly
        self.q.reset()
        self._prepare(resample_poly(x16, 1, 2))
        self._hats, self._raw = [], []
        return hb.SottoV38.encode(self, x16)


def load_wb(d=WB):
    """The 16 kHz voices of the v3.8 page and the FARGAN study (LibriSpeech, CC BY 4.0)."""
    import glob, soundfile as sf
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*__original16.flac"))):
        x, fs = sf.read(f)
        assert fs == 16000
        out[os.path.basename(f)[:-len("__original16.flac")]] = x
    return out


def _one_wb(args):
    from pesq import pesq
    q, name, x = args
    lab = Lab38(q)
    bits = lab.encode(x)
    y = lab.decode_audio16(bits, n16=len(x))
    n = min(len(x), len(y))
    raw, hat = np.array(lab._raw), np.array(lab._hats)
    return name, dict(wb=float(pesq(16000, x[:n], y[:n], "wb")), nb16=float(pesq(16000, x[:n], y[:n], "nb")),
                      sd=float(np.mean((raw - hat) ** 2)))


def score_wb(q, clips=None, procs=4):
    clips = clips or load_wb()
    with Pool(procs) as p:
        res = dict(p.map(_one_wb, [(q, n, x) for n, x in clips.items()]))
    res["_mean"] = {k: float(np.mean([r[k] for r in res.values()])) for k in ("wb", "nb16", "sd")}
    return res


def load_clean(d=CLEAN):
    return ar.load_clips(d)


def load_nb31():
    """31 held-out 8 kHz voices: the 16 clean voices, the 12 Speech Commands counting clips
    and the 3 voices of the listening page (none of them in any training set)."""
    out = {}
    for d in (CLEAN, os.path.join(os.path.dirname(CLEAN), "samples-sc"), os.path.join(os.path.dirname(CLEAN), "samples15")):
        out.update(ar.load_clips(d))
    return out


def _one(args):
    q, name, x = args
    lab = Lab(q)
    bits = lab.encode(x)
    y = vl.synthesise(lab.decode(bits))
    p, e = ar.score(x, y, ar.CODEC_DELAY)
    raw, hat = np.array(lab._raw), np.array(lab._hats)
    return name, dict(pesq=float(p), estoi=float(e), sd=float(np.mean((raw - hat) ** 2)), n=len(raw))


def score(q, clips=None, procs=4):
    """-> {clip: dict(pesq, estoi, sd)} plus '_mean'."""
    clips = clips or load_clean()
    with Pool(procs) as p:
        res = dict(p.map(_one, [(q, n, x) for n, x in clips.items()]))
    res["_mean"] = {k: float(np.mean([r[k] for r in res.values()])) for k in ("pesq", "estoi", "sd")}
    return res


def shapes10(x8, pitch="tracked4"):
    """(shapes, energy dB) of every 10 ms frame, padded to an even count like encode()."""
    m = vl.analyse(x8, pitch)
    if len(m) % 2:
        m = np.concatenate([m, m[-1:]])
    rk = vl.to_rate_k(m)
    en = vl.frame_energy_db(vl.from_rate_k(m, rk))
    return rk - rk.mean(1, keepdims=True), en


def shapes_of(clips, pitch="tracked4"):
    """Mean-removed rate-K shapes of the 20 ms frames each encoder sees, per clip."""
    out = {}
    for n, x in clips.items():
        m = vl.analyse(x, pitch)
        if len(m) % 2:
            m = np.concatenate([m, m[-1:]])
        rk = vl.to_rate_k(m)[::2]
        out[n] = rk - rk.mean(1, keepdims=True)
    return out


W = dict(gamma=0.5, floor=40.0)
ROWS = [("v3.8 encoder before 2026-11-19 (plain squared error)", lambda: Shipped()),
        ("v3.8 encoder now: weighted final pick", lambda: Shipped(wpick=W)),
        ("weighted search from stage 3 + weighted pick", lambda: Shipped(wsearch=dict(W, from_stage=2))),
        ("weighted search in every stage", lambda: Shipped(wsearch=dict(W, from_stage=0))),
        ("unquantized shape (ceiling)", lambda: Oracle())]


def main():
    """Score each row on the 31 held-out 8 kHz voices (8 kHz core) and the 10 v3.8 page
    voices (full v3.8 at 16 kHz); --codebook NAME=PATH adds rows for other codebooks, plain
    and with the weighted pick."""
    import argparse, json
    a = argparse.ArgumentParser()
    a.add_argument("--codebook", action="append", default=[])
    a.add_argument("--json")
    a = a.parse_args()
    rows = list(ROWS)
    for cb in a.codebook:
        n, pth = cb.split("=", 1)
        rows += [(f"{n}, plain", lambda p=pth: Shipped(path=p)), (f"{n}, weighted pick", lambda p=pth: Shipped(path=p, wpick=W))]
    nb, wb = load_nb31(), load_wb()
    out, ref = [], None
    for name, mk in rows:
        r8, r16 = score(mk(), nb), score_wb(mk(), wb)
        if ref is None:
            ref = (r8, r16)
        row = dict(name=name, nb31_pesq=r8["_mean"]["pesq"], nb31_estoi=r8["_mean"]["estoi"],
                   nb31_better=int(sum(r8[c]["pesq"] > ref[0][c]["pesq"] for c in nb)),
                   shape_err_db2=r8["_mean"]["sd"], wb10_pesq=r16["_mean"]["wb"], wb10_nb=r16["_mean"]["nb16"],
                   wb10_better=int(sum(r16[c]["wb"] > ref[1][c]["wb"] for c in wb)),
                   per_clip=dict(nb31={c: r8[c]["pesq"] for c in nb}, wb10={c: r16[c]["wb"] for c in wb}))
        out.append(row)
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items() if k != "per_clip"}), flush=True)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
