"""Oracle lab for the sotto encoder: take Codec 2's sinusoidal model (from c2sim --modelout),
change or quantize it in Python, and synthesise with c2sim --modelin --phase0 --postfilter.

The first candidate encoder ("sotto v0", 48 bits / 20 ms, memoryless):
  voicing  2 bits  (one per 10 ms subframe, as Codec 2 2400)
  Wo       7 bits  (log-uniform between Codec 2's Wo_min and Wo_max)
  energy   5 bits  (mean of the rate-K dB vector)
  shape   34 bits  (DCT of the mean-removed 20-point mel-spaced envelope, scalar
                    quantizers with trained step sizes and greedy bit allocation)
It replaces Codec 2 2400's LPC-10 / LSP envelope with a rate-K envelope, which the oracle
ladder showed is the biggest single loss.

Usage: python sim/vocoder_lab.py [--samples DIR]
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio_race as ar

MAX_AMP = 160
MODEL = np.dtype([("Wo", "<f4"), ("L", "<i4"), ("A", "<f4", MAX_AMP + 1),
                  ("phi", "<f4", MAX_AMP + 1), ("voiced", "<i4")])
FS = 8000
WO_MIN, WO_MAX = 2 * np.pi / 160, 2 * np.pi / 20
K = 20


def _mel(f):
    return np.floor(2595 * np.log10(1 + f / 700) + 0.5)


KFREQ = 700 * (10 ** (np.linspace(_mel(200), _mel(3700), K) / 2595) - 1)   # Hz
_n = np.arange(K)
DCT = np.sqrt(2 / K) * np.cos(np.pi * (_n[None, :] + 0.5) * _n[:, None] / K)
DCT[0] /= np.sqrt(2)                                     # orthonormal DCT-II


# ---------------------------------------------------------------- c2sim I/O
TRACK = {}
TRACK2 = {}


def analyse(x, pitch="c2"):
    """8 kHz float speech -> MODEL records, one per 10 ms. pitch="tracked" corrects
    Codec 2's octave errors with sinusoid.track_pitch and re-estimates the amplitudes."""
    if pitch == "tracked":
        import sinusoid as sn
        m = analyse(x)
        xi = np.round(x * 32767)
        Sw = sn.spectra(xi)
        wo = sn.track_pitch(Sw, m["Wo"], m["voiced"], **TRACK)
        return sn.analyse(xi, wo, voicing=m["voiced"], do_refine=False)[:len(m)]
    if pitch == "tracked2":
        # v2: pitch up to 500 Hz, and voicing re-checked at the corrected pitch
        import sinusoid as sn
        m = analyse(x)
        xi = np.round(x * 32767)
        Sw = sn.spectra(xi)
        wo, v = sn.track_pitch_voicing(Sw, m["Wo"], m["voiced"], **TRACK2)
        return sn.analyse(xi, wo, voicing=v, do_refine=False)[:len(m)]
    with tempfile.TemporaryDirectory() as d:
        np.round(x * 32767).astype("<i2").tofile(f"{d}/in.raw")
        subprocess.run([f"{ar.C2BIN}/c2sim", f"{d}/in.raw", "--modelout", f"{d}/m.bin"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return np.fromfile(f"{d}/m.bin", MODEL)


def synthesise(m, postfilter=True):
    with tempfile.TemporaryDirectory() as d:
        n = len(m)
        np.zeros(n * 80, "<i2").tofile(f"{d}/in.raw")
        m.tofile(f"{d}/m.bin")
        args = [f"{ar.C2BIN}/c2sim", f"{d}/in.raw", "--modelin", f"{d}/m.bin", "--phase0",
                "-o", f"{d}/out.raw"] + (["--postfilter"] if postfilter else [])
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


# ---------------------------------------------------------------- rate-K envelope
def to_rate_k(m):
    out = np.zeros((len(m), K))
    for i, r in enumerate(m):
        L = r["L"]
        f = np.arange(1, L + 1) * r["Wo"] * FS / (2 * np.pi)
        a = 20 * np.log10(r["A"][1:L + 1] + 1e-16)
        a = np.maximum(a, a.max() - 50)
        out[i] = np.interp(KFREQ, f, a)
    return out


def from_rate_k(m, rk):
    m = m.copy()
    for i in range(len(m)):
        L = m[i]["L"]
        f = np.arange(1, L + 1) * m[i]["Wo"] * FS / (2 * np.pi)
        A = np.zeros(MAX_AMP + 1, np.float32)
        A[1:L + 1] = 10 ** (np.interp(f, KFREQ, rk[i]) / 20)
        m[i]["A"] = A
    return m


def set_wo(m, wo, voiced):
    m = m.copy()
    m["Wo"] = wo
    m["L"] = np.floor(np.pi / wo).astype(int)
    m["voiced"] = voiced
    return m


def decimate_interp(v, axis_vals=None):
    """Keep every 2nd frame (20 ms) and linearly interpolate the frames in between."""
    out = v.copy()
    n = len(v)
    for i in range(1, n, 2):
        nxt = v[i + 1] if i + 1 < n else v[i - 1]
        out[i] = 0.5 * (v[i - 1] + nxt)
    return out


def interp_wo(wo, voiced):
    """Codec 2 style: odd 10 ms subframes take Wo from the 20 ms frames either side."""
    out = wo.copy()
    for i in range(1, len(wo), 2):
        a, b = i - 1, min(i + 1, len(wo) - 1)
        if voiced[i] and voiced[a] and voiced[b]:
            out[i] = 0.5 * (wo[a] + wo[b])
        elif voiced[i]:
            out[i] = wo[a] if voiced[a] else wo[b]
        else:
            out[i] = WO_MIN * 2 if not voiced[i] else out[i]
    return out


# ---------------------------------------------------------------- quantizers
def q_uniform(x, lo, hi, bits):
    n = 2 ** bits
    idx = np.clip(np.round((x - lo) / (hi - lo) * (n - 1)), 0, n - 1).astype(int)
    return idx, lo + idx * (hi - lo) / (n - 1)


def q_wo(wo, bits=7, hi=WO_MAX):
    idx, lw = q_uniform(np.log(wo), np.log(WO_MIN), np.log(hi), bits)
    return idx, np.exp(lw)


class ShapeQ:
    """DCT coefficients 1..K-1 of the mean-removed envelope, uniform scalar quantizers."""

    def __init__(self, train, total_bits=34, max_bits=7):
        c = train @ DCT.T
        self.c = c[:, 1:]
        self.steps = {}
        self.bits = np.zeros(K - 1, int)
        # MSE for each coefficient at each bit count, with the best step found by search
        self.mse = np.zeros((K - 1, max_bits + 1))
        for j in range(K - 1):
            x = self.c[:, j]
            self.mse[j, 0] = np.mean(x ** 2)
            for b in range(1, max_bits + 1):
                best = None
                for s in np.std(x) * np.geomspace(0.02, 3, 60):
                    e = np.mean((x - self._q(x, s, b)) ** 2)
                    if best is None or e < best[0]:
                        best = (e, s)
                self.mse[j, b], self.steps[(j, b)] = best
        for _ in range(total_bits):            # greedy: give each bit where it cuts MSE most
            gain = [self.mse[j, self.bits[j]] - self.mse[j, self.bits[j] + 1]
                    if self.bits[j] < max_bits else -1 for j in range(K - 1)]
            self.bits[int(np.argmax(gain))] += 1

    @staticmethod
    def _q(x, s, b):
        n = 2 ** b
        idx = np.clip(np.floor(x / s + n / 2), 0, n - 1)
        return (idx - n / 2 + 0.5) * s

    def quantize(self, shape):
        c = shape @ DCT.T
        cq = np.zeros_like(c)
        for j in range(K - 1):
            b = self.bits[j]
            if b:
                cq[:, j + 1] = self._q(c[:, j + 1], self.steps[(j, b)], b)
        return cq @ DCT


def postfilter_rk(shape, gain=1.5):
    """newamp1-style envelope postfilter on mean-removed rate-K vectors (energy kept)."""
    pre = 20 * np.log10(KFREQ / 300.0)
    v = shape + pre
    e0 = np.log10(np.sum(10 ** (v / 10), 1, keepdims=True))
    v = v * gain
    e1 = np.log10(np.sum(10 ** (v / 10), 1, keepdims=True))
    return v - 10 * (e1 - e0) - pre


def sotto_v0(m, shapeq, e_lo=0.0, e_hi=80.0, pf=0.0, alpha=0.0):
    """Quantize one clip's model with the 48-bit v0 scheme, decode, return new MODEL.
    pf: envelope postfilter gain (0 = off). alpha: inter-frame prediction of the shape
    (0 = memoryless; the ShapeQ must then be trained on prediction residuals)."""
    rk = to_rate_k(m)
    mean = rk.mean(1, keepdims=True)
    shape = rk - mean
    voiced = m["voiced"].copy()
    _, wo = q_wo(np.where(voiced > 0, m["Wo"], m["Wo"]), 7)
    _, meanq = q_uniform(mean[:, 0], e_lo, e_hi, 5)
    if alpha:
        shapeq_ = np.zeros_like(shape)
        prev = np.zeros(K)
        for i in range(0, len(shape), 2):
            shapeq_[i] = shapeq.quantize((shape[i] - alpha * prev)[None])[0] + alpha * prev
            prev = shapeq_[i]
    else:
        shapeq_ = shapeq.quantize(shape)
    if pf:
        shapeq_ = postfilter_rk(shapeq_, pf)
    rkq = decimate_interp(shapeq_ + meanq[:, None])
    wo = interp_wo(np.asarray(wo, float), voiced)
    return from_rate_k(set_wo(m, wo, voiced), rkq)


def training_set(pitch="c2"):
    """Rate-K shapes from Codec 2's test recordings, excluding the 15 s ve9qrp test window."""
    raw = os.path.join(os.path.dirname(HERE), "codec", "codec2", "raw")
    xs = []
    for f in ("hts1.raw", "kristoff.raw", "ve9qrp.raw"):
        x = np.fromfile(os.path.join(raw, f), "<i2").astype(float) / 32768
        if f == "ve9qrp.raw":
            x = np.concatenate([x[:int(6.4 * FS)], x[int(21.4 * FS):]])
        xs.append(x)
    rk = np.concatenate([to_rate_k(analyse(x, pitch)) for x in xs])
    rk = rk[rk.mean(1) > np.percentile(rk.mean(1), 20)]          # drop silence
    return rk - rk.mean(1, keepdims=True)


def predictive_training(shapes, alpha):
    """Residuals of first-order prediction at 20 ms spacing (open loop, for step training)."""
    s20 = shapes[::2]
    return s20[1:] - alpha * s20[:-1]


def main(samples):
    clips = ar.load_clips(samples)
    tr = training_set()
    sq = ShapeQ(tr)
    sqp = ShapeQ(predictive_training(tr, 0.5))
    print("shape bits per DCT coefficient:", sq.bits.tolist(), "=", sq.bits.sum())
    rows = {}
    for c, x in clips.items():
        m = analyse(x)
        rk = to_rate_k(m)
        variants = {
            "model, phase0+pf": m,
            "rate-K envelope (unquantized)": from_rate_k(m, rk),
            "rate-K, 20 ms + interp": from_rate_k(m, decimate_interp(rk)),
            "sotto v0 (48 bits)": sotto_v0(m, sq),
            "v0 + envelope postfilter 1.5": sotto_v0(m, sq, pf=1.5),
            "v0 + prediction 0.5": sotto_v0(m, sqp, alpha=0.5),
            "v0 + prediction 0.5 + pf 1.5": sotto_v0(m, sqp, alpha=0.5, pf=1.5),
        }
        rows[c] = {}
        for name, mm in variants.items():
            y = synthesise(mm)
            rows[c][name] = ar.score(x, y, ar.best_lag(x, y))
        y = ar.c2dec(ar.c2enc(np.round(x * 32767)))
        rows[c]["Codec 2 2400 (c2enc/c2dec)"] = ar.score(x, y, ar.best_lag(x, y))
    names = list(next(iter(rows.values())))
    print(f"{'variant':32s}" + "".join(f"{c[:18]:>20s}" for c in clips))
    for n in names:
        print(f"{n:32s}" + "".join(f"{rows[c][n][0]:12.2f} ({rows[c][n][1]:.2f})" for c in clips))
    return rows


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--samples", default=ar.SAMPLES)
    main(a.parse_args().samples)


# ---------------------------------------------------------------- v0 as a bitstream codec
def frame_energy_db(m):
    return np.array([10 * np.log10(np.sum(r["A"][1:r["L"] + 1] ** 2) + 1e-9) for r in m])


def set_energy(m, e_db):
    m = m.copy()
    for i in range(len(m)):
        L = m[i]["L"]
        e = np.sum(m[i]["A"][1:L + 1] ** 2) + 1e-12
        m[i]["A"][1:L + 1] *= np.sqrt(10 ** (e_db[i] / 10) / e)
    return m


class SottoV0:
    """Memoryless 48-bit / 20 ms codec: bits = voicing(2) | Wo(7) | energy(5) | shape(34).
    Most sensitive fields first. Encoder runs c2sim analysis; decoder needs only the bits.
    The energy field is the frame energy (sum of harmonic powers), so the decoded level
    matches the input whatever the envelope smoothing does."""

    E_LO, E_HI = 10.0, 80.0
    WO_HI = WO_MAX

    def __init__(self, shapeq=None, pf=1.5, pitch="c2"):
        self.pitch = pitch
        self.sq = shapeq or ShapeQ(training_set(pitch))
        self.pf = pf
        self.fields = [b for b in self.sq.bits if b]

    def _shape_idx(self, shape):
        c = shape @ DCT.T
        idx = []
        for j in range(K - 1):
            b = self.sq.bits[j]
            if b:
                n = 2 ** b
                idx.append(int(np.clip(np.floor(c[j + 1] / self.sq.steps[(j, b)] + n / 2), 0, n - 1)))
        return idx

    def _shape_val(self, idx):
        c = np.zeros(K)
        it = iter(idx)
        for j in range(K - 1):
            b = self.sq.bits[j]
            if b:
                c[j + 1] = (next(it) - 2 ** b / 2 + 0.5) * self.sq.steps[(j, b)]
        return c @ DCT

    @staticmethod
    def _pack(vals_bits):
        out = []
        for v, b in vals_bits:
            out += [(int(v) >> (b - 1 - i)) & 1 for i in range(b)]
        return out

    def encode(self, x):
        m = analyse(x, self.pitch)
        if len(m) % 2:
            m = np.concatenate([m, m[-1:]])
        rk = to_rate_k(m)
        en = frame_energy_db(m)
        frames = []
        for i in range(0, len(m), 2):
            v = [int(m[i]["voiced"] > 0), int(m[i + 1]["voiced"] > 0)]
            wi, _ = q_wo(np.array([m[i]["Wo"]]), hi=self.WO_HI)
            ei, _ = q_uniform(np.array([en[i]]), self.E_LO, self.E_HI, 5)
            si = self._shape_idx(rk[i] - rk[i].mean())
            frames.append(self._pack([(v[0], 1), (v[1], 1), (wi[0], 7), (ei[0], 5)]
                                     + list(zip(si, self.fields))))
        return np.array(frames, np.int8)

    def decode(self, bits):
        n = len(bits)
        voiced = np.zeros(2 * n, int)
        wo = np.zeros(2 * n)
        rk = np.zeros((2 * n, K))
        en = np.zeros(2 * n)
        for f, b in enumerate(np.asarray(bits)):
            p = 0

            def take(k):
                nonlocal p
                v = int("".join(map(str, b[p:p + k])), 2)
                p += k
                return v
            voiced[2 * f], voiced[2 * f + 1] = take(1), take(1)
            wo[2 * f] = np.exp(np.log(WO_MIN) + take(7) * (np.log(self.WO_HI) - np.log(WO_MIN)) / 127)
            en[2 * f] = self.E_LO + take(5) * (self.E_HI - self.E_LO) / 31
            shape = self._shape_val([take(bb) for bb in self.fields])
            if self.pf:
                shape = postfilter_rk(shape[None], self.pf)[0]
            rk[2 * f] = shape
        rk = decimate_interp(rk)
        en = decimate_interp(en)
        wo[1::2] = wo[0::2]
        wo = interp_wo(wo, voiced)
        wo = np.where(voiced > 0, wo, np.maximum(wo, WO_MIN))
        m = np.zeros(2 * n, MODEL)
        m = set_wo(m, wo, voiced)
        return set_energy(from_rate_k(m, rk), en)

    def decode_audio(self, bits):
        return synthesise(self.decode(bits))


# ---------------------------------------------------------------- v1: tracked pitch, predicted shape
def training_pairs(pitch="tracked"):
    """DCT coefficient vectors of consecutive 20 ms frames (both non-silent) from the
    training recordings, for fitting the shape predictor."""
    raw = os.path.join(os.path.dirname(HERE), "codec", "codec2", "raw")
    prev, cur = [], []
    for f in ("hts1.raw", "kristoff.raw", "ve9qrp.raw"):
        x = np.fromfile(os.path.join(raw, f), "<i2").astype(float) / 32768
        segs = [x] if f != "ve9qrp.raw" else [x[:int(6.4 * FS)], x[int(21.4 * FS):]]
        for s in segs:
            rk = to_rate_k(analyse(s, pitch))[::2]
            mean = rk.mean(1)
            c = (rk - mean[:, None]) @ DCT.T
            live = mean > np.percentile(mean, 20)
            ok = live[1:] & live[:-1]
            prev.append(c[:-1][ok])
            cur.append(c[1:][ok])
    return np.concatenate(prev), np.concatenate(cur)


class SottoV1(SottoV0):
    """v0 with the octave-corrected pitch track and a first-order predictor on the shape's
    DCT coefficients (per-coefficient gains alpha_j, fitted on the training set and scaled
    by `shrink` so channel errors die out quickly). The shape quantizer is trained on the
    prediction residuals. Bit layout is unchanged from v0.

    decode(bits, good) leaves the predictor state untouched on frames flagged bad, so a
    concealed frame doesn't feed its residual in again."""

    def __init__(self, shrink=0.8, pf=1.5, pitch="tracked", max_alpha=0.8):
        p, c = training_pairs(pitch)
        a = np.sum(p * c, 0) / np.maximum(np.sum(p * p, 0), 1e-9)
        self.alpha = np.clip(a * shrink, 0, max_alpha)
        self.alpha[0] = 0
        res = (c - self.alpha * p) @ DCT
        super().__init__(ShapeQ(res), pf=pf, pitch=pitch)

    def _shape_idx_c(self, c):
        return self._shape_idx(c @ DCT)

    def encode(self, x):
        m = analyse(x, self.pitch)
        if len(m) % 2:
            m = np.concatenate([m, m[-1:]])
        rk = to_rate_k(m)
        en = frame_energy_db(m)
        prev = np.zeros(K)
        frames = []
        for i in range(0, len(m), 2):
            v = [int(m[i]["voiced"] > 0), int(m[i + 1]["voiced"] > 0)]
            wi, _ = q_wo(np.array([m[i]["Wo"]]))
            ei, _ = q_uniform(np.array([en[i]]), self.E_LO, self.E_HI, 5)
            c = (rk[i] - rk[i].mean()) @ DCT.T
            pred = self.alpha * prev
            si = self._shape_idx_c(c - pred)
            prev = pred + self._shape_val(si) @ DCT.T
            frames.append(self._pack([(v[0], 1), (v[1], 1), (wi[0], 7), (ei[0], 5)]
                                     + list(zip(si, self.fields))))
        return np.array(frames, np.int8)

    def decode(self, bits, good=None):
        bits = np.asarray(bits)
        good = np.ones(len(bits), bool) if good is None else np.asarray(good, bool)
        nshape = sum(self.fields)
        prev = np.zeros(K)
        out = bits.copy()
        shapes = []
        for f, b in enumerate(bits):
            if good[f]:
                p = 14
                idx = []
                for bb in self.fields:
                    idx.append(int("".join(map(str, b[p:p + bb])), 2))
                    p += bb
                prev = self.alpha * prev + self._shape_val(idx) @ DCT.T
            shapes.append(prev.copy())
        # reuse v0's decoder with a memoryless shape quantizer that returns these shapes
        m = SottoV0.decode(self, out)
        rk = np.zeros((2 * len(bits), K))
        rk[0::2] = np.array(shapes) @ DCT
        if self.pf:
            rk[0::2] = postfilter_rk(rk[0::2], self.pf)
        rk = decimate_interp(rk)
        en = frame_energy_db(m)
        return set_energy(from_rate_k(m, rk), en)


class SottoV2(SottoV0):
    """v1 plus pitch up to 500 Hz (the 7-bit Wo field now spans 50-500 Hz) and voicing
    re-checked at the corrected pitch, with voiced runs under 30 ms dropped."""

    WO_HI = 2 * np.pi / 16

    def __init__(self, shapeq=None, pf=1.5, quiet=None):
        super().__init__(shapeq, pf=pf, pitch="tracked2")
        self.quiet = quiet          # dict(margin, tilt, atten): see soften_pauses

    def decode(self, bits):
        m = super().decode(bits)
        return soften_pauses(m, **self.quiet) if self.quiet else m


def soften_pauses(m, margin=25.0, tilt=6.0, atten=0.0, release=0.995):
    """Decoder-only treatment of background between words: unvoiced frames more than
    `margin` dB below the recent speech peak get a high-frequency roll-off of `tilt` dB per
    octave above 1 kHz and `atten` dB less level. Codec 2's softer, darker pauses were
    preferred by a listener over v2's flat hiss."""
    m = m.copy()
    en = frame_energy_db(m)
    peak = -1e9
    for i in range(len(m)):
        peak = max(en[i], peak * release + (1 - release) * en[i] if peak > -1e8 else en[i])
        if m[i]["voiced"] or en[i] > peak - margin:
            continue
        L = m[i]["L"]
        f = np.arange(1, L + 1) * m[i]["Wo"] * FS / (2 * np.pi)
        g = -tilt * np.log2(np.maximum(f, 1000) / 1000)
        a = m[i]["A"][1:L + 1] * 10 ** (g / 20)
        a *= np.sqrt(np.sum(m[i]["A"][1:L + 1] ** 2) / (np.sum(a ** 2) + 1e-12)) * 10 ** (-atten / 20)
        m[i]["A"][1:L + 1] = a
    return m
