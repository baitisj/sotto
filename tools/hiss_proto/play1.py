"""Decoder-only experiments on the cached v3.8 bits (same bitstream): unvoiced LF roll-off
under the 50 Hz noise spacing, and a decoder-side pitch smoother for creaky stretches.
Usage: play1.py <clip> -> one row of PESQ-NB per variant."""
import sys; sys.path.insert(0, '/home/claude/sotto/sim')
import numpy as np, soundfile as sf, vocoder_lab as vl, hiss_band as hb
from scipy.signal import resample_poly, medfilt
from pesq import pesq
vl.TRACK2['lag'] = 8
clip = sys.argv[1]
x = sf.read(f'/tmp/claude-0/hiss/clips16/{clip}.wav')[0]; x = x[:len(x) // 320 * 320]; x8 = resample_poly(x, 1, 2)
b = np.load(f'/tmp/claude-0/hiss/bits/{clip}.npz')['bits']

class Play(hb.SottoV38):
    lf = None        # Hz: unvoiced components below this get a 12 dB/oct roll-off (None = off)
    lf_zero = False  # zero them instead
    fry_thr = None   # decoder pitch smoother: |log Wo - median5| above this -> median
    fry_gate = None  # dB below the voiced run's peak energy needed for the smoother to act

    def _model_hook(self, m, rk, en):
        if self.fry_thr is not None:
            m = self._fry_smooth(m, rk, en)
        u = np.where(m["voiced"] == 0)[0]
        if len(u):
            mu = vl.set_wo(m[u], np.full(len(u), hb.W50), np.zeros(len(u), int))
            mu = vl.from_rate_k(mu, rk[u])
            if self.lf:
                for r in mu:
                    f = np.arange(1, r["L"] + 1) * r["Wo"] * vl.FS / (2 * np.pi)
                    g = np.where(f < self.lf, 1e-3 if self.lf_zero else (f / self.lf) ** 2, 1.0)
                    r["A"][1:r["L"] + 1] *= g
            m[u] = vl.set_energy(mu, en[u])
            for k in u:
                if rk[k, hb.KLO].mean() - rk[k, hb.KHI].mean() < 0:
                    m[k]["A"] *= 10 ** (hb.UV_GAIN / 20)
        return m

    def _fry_smooth(self, m, rk, en):
        v = m["voiced"] > 0
        wo = m["Wo"].copy()
        lw = np.log(wo)
        changed = np.zeros(len(m), bool)
        # voiced runs of 10 ms frames
        i = 0
        while i < len(m):
            if not v[i]:
                i += 1; continue
            j = i
            while j < len(m) and v[j]:
                j += 1
            if j - i >= 5:
                seg = lw[i:j]
                med = medfilt(seg, 5)
                med[:2] = seg[:2]; med[-2:] = seg[-2:]
                dev = np.abs(seg - med) > self.fry_thr
                if self.fry_gate is not None:
                    dev &= en[i:j] < en[i:j].max() - self.fry_gate
                lw[i:j] = np.where(dev, med, seg)
                changed[i:j] = dev
            i = j
        if changed.any():
            idx = np.where(changed)[0]
            mv = m[idx].copy()
            mv["Wo"] = np.exp(lw[idx]); mv["L"] = np.floor(np.pi / mv["Wo"]).astype(int)
            mv = vl.set_energy(vl.from_rate_k(mv, rk[idx]), en[idx])
            for q, k in enumerate(idx):
                if m[k]["voiced"] >= 2:
                    mv[q]["voiced"] = vl.mixed_cutoff(mv[q]["Wo"])
            m[idx] = mv
        self.n_changed = int(changed.sum())
        return m

DEC = dict(vowel='speaker', vowel_shape='fine', voiced_trim=-5, blend=True, release_ms=0, keep_mixed=True)
def sc(d):
    y = vl.synthesise(d.decode(b))[vl.ar.CODEC_DELAY:]; n = min(len(y), len(x8))
    return pesq(8000, x8[:n], y[:n], 'nb')
vars_ = [('base', {}), ('lf150', dict(lf=150)), ('lf250', dict(lf=250)), ('z150', dict(lf=150, lf_zero=True)),
         ('fry.12', dict(fry_thr=0.12)), ('fry.2', dict(fry_thr=0.2)), ('fry.12g6', dict(fry_thr=0.12, fry_gate=6)),
         ('fry.08g6', dict(fry_thr=0.08, fry_gate=6))]
out = []
for k, o in vars_:
    d = Play(**DEC)
    for a, val in o.items(): setattr(d, a, val)
    s = sc(d); extra = f"({d.n_changed})" if hasattr(d, 'n_changed') else ''
    out.append(f"{k} {s:.3f}{extra}")
print(f"{clip:22s} " + '  '.join(out), flush=True)
