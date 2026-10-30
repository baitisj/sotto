"""C4FM soft modem: 4800 baud 4-level FSK as baseband audio.

The modulator turns YSF frame bits into the baseband signal that drives an FM transmitter's
VCO (a radio's 9600 data input, or an SDR's FM modulator). The demodulator takes the FM
discriminator output (a radio's 9600 data output, or an SDR's FM demodulator), finds frames
by their sync word and returns soft bits (LLRs, positive = 0) for each 960-bit frame.

It is meant to cope with what a sound card does to the signal: unknown level and polarity,
DC offset and AC coupling, sample-clock error, and 44.1 kHz rates.
"""
from dataclasses import dataclass
from fractions import Fraction
import numpy as np
from scipy import signal

from . import ysf

BAUD = 4800
FS = 48000
SPS = FS // BAUD
DEV_HZ = 600.0                      # deviation per level unit: symbols at +-600 / +-1800 Hz
LEVELS = np.array([3.0, 1.0, -1.0, -3.0])
LEVEL_BITS = np.array([[0, 1], [0, 0], [1, 0], [1, 1]], np.int8)   # dibit for each level


def dibits_to_levels(bits):
    b = np.asarray(bits).reshape(-1, 2)
    lut = np.array([1.0, 3.0, -1.0, -3.0])          # index b0*2 + b1: 00->+1 01->+3 10->-1 11->-3
    return lut[b[:, 0] * 2 + b[:, 1]]


def rrc(alpha=0.2, sps=SPS, span=8):
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    h = np.zeros_like(t)
    for i, x in enumerate(t):
        if abs(x) < 1e-9:
            h[i] = 1 + alpha * (4 / np.pi - 1)
        elif abs(abs(x) - 1 / (4 * alpha)) < 1e-9:
            h[i] = alpha / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                                         + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
        else:
            h[i] = (np.sin(np.pi * x * (1 - alpha)) + 4 * alpha * x * np.cos(np.pi * x * (1 + alpha))) \
                   / (np.pi * x * (1 - (4 * alpha * x) ** 2))
    return h


_RRC = rrc()
_RRC_D = (len(_RRC) - 1) // 2
# TX pulse scaled so a run of equal symbols sits exactly at its level; the receiver fits
# the level itself, so its filter gain doesn't matter.
_TX = _RRC / _RRC[_RRC_D % SPS::SPS].sum()


def _resample(x, fs_in, fs_out):
    if fs_in == fs_out:
        return np.asarray(x, float)
    r = Fraction(fs_out, fs_in).limit_denominator(1000)
    return signal.resample_poly(np.asarray(x, float), r.numerator, r.denominator)


class Modulator:
    def __init__(self, fs=FS):
        self.fs = fs

    def modulate(self, bits, lead_s=0.05, tail_s=0.05):
        """Frame bits -> instantaneous frequency in Hz at self.fs (feed to FM or scale to audio)."""
        lv = dibits_to_levels(bits) * DEV_HZ
        lead, tail = int(lead_s * FS), int(tail_s * FS)
        imp = np.zeros(lead + len(lv) * SPS + tail)
        imp[lead:lead + len(lv) * SPS:SPS] = lv
        f = np.convolve(imp, _TX)[_RRC_D:_RRC_D + len(imp)]
        return _resample(f, FS, self.fs)


@dataclass
class RxFrame:
    start: float           # sample index (at 48 kHz) of the first sync symbol
    rho: float             # sync correlation, -1..1 (negative = inverted audio)
    llr: np.ndarray        # 960 soft bits
    fich: object           # ysf.FICH or None
    level: tuple           # fitted (scale, offset): input units per level unit, and DC
    snr_db: float          # symbol SNR estimate


class Demodulator:
    """Frame-synchronous C4FM receiver with a flywheel.

    Hunting: candidate sync peaks (|rho| > hunt_rho) are accepted only if the FICH decodes.
    Locked: the next frame is looked for 480 symbols later within +-search samples, and is
    passed on even when its FICH fails. Lock is dropped on a terminator or after max_miss
    weak frames in a row.
    """

    def __init__(self, fs=FS, hunt_rho=0.6, search=5, max_miss=8):
        self.fs, self.hunt_rho, self.search, self.max_miss = fs, hunt_rho, search, max_miss
        s = dibits_to_levels(ysf.SYNC)
        self.sync = s - s.mean()

    # -- helpers
    def _rho(self, y):
        n_win = (len(self.sync) - 1) * SPS + 1
        rho = np.zeros(len(y))
        L = len(self.sync)
        for p in range(SPS):
            yp = y[p::SPS]
            if len(yp) < L:
                continue
            num = np.correlate(yp, self.sync, "valid")
            c1 = np.convolve(yp, np.ones(L), "valid")
            c2 = np.convolve(yp ** 2, np.ones(L), "valid")
            var = np.maximum(c2 - c1 ** 2 / L, 1e-12)
            r = num / np.sqrt(var * np.sum(self.sync ** 2))
            rho[p::SPS][:len(r)] = r
        rho[len(y) - n_win + 1:] = 0
        return rho

    @staticmethod
    def _interp(y, t):
        i = np.floor(t).astype(int)
        f = t - i
        ok = (i >= 0) & (i + 1 < len(y))
        out = np.zeros(len(t))
        out[ok] = y[i[ok]] * (1 - f[ok]) + y[i[ok] + 1] * f[ok]
        return out, ok

    def _frame(self, y, t0, sps, prior=None):
        t = t0 + np.arange(ysf.FRAME_SYMS) * sps
        r, ok = self._interp(y, t)
        if ok.mean() < 0.9:
            return None
        s_sync = dibits_to_levels(ysf.SYNC)
        a, b = np.linalg.lstsq(np.stack([s_sync, np.ones(20)], 1), r[:20], rcond=None)[0]
        starts = [(a, b)] + ([prior] if prior is not None else [])
        fits = [self._fit(r, a0, b0, s_sync) for a0, b0 in starts if abs(a0) > 1e-12]
        if not fits:
            return None
        z, a, b, res = min(fits, key=lambda f: f[3].mean())
        d2 = (z[:, None] - LEVELS[None, :]) ** 2
        s2 = np.convolve(res, np.ones(24) / 24, "same") + 0.02
        llr = np.zeros((ysf.FRAME_SYMS, 2))
        for k in range(2):
            m0 = np.min(np.where(LEVEL_BITS[None, :, k] == 0, d2, np.inf), 1)
            m1 = np.min(np.where(LEVEL_BITS[None, :, k] == 1, d2, np.inf), 1)
            llr[:, k] = (m1 - m0) / (2 * s2)
        snr = 10 * np.log10(5.0 / max(res.mean(), 1e-6))   # mean level power 5
        return llr.reshape(-1), (a, b), snr

    @staticmethod
    def _fit(r, a, b, s_sync):
        """Decision-directed fit of r = a * level + DC (with a linear DC drift over the frame)."""
        kk = np.arange(len(r)) / len(r) - 0.5
        bb = np.full(len(r), b)
        for _ in range(2):
            z = (r - bb) / a
            sh = LEVELS[np.argmin(np.abs(z[:, None] - LEVELS[None, :]), 1)]
            sh[:20] = s_sync
            a2, b0, b1 = np.linalg.lstsq(np.stack([sh, np.ones_like(kk), kk], 1), r, rcond=None)[0]
            if abs(a2) < 1e-12:
                break
            a, bb = a2, b0 + b1 * kk
        z = (r - bb) / a
        res = np.min((z[:, None] - LEVELS[None, :]) ** 2, 1)
        return z, a, float(bb.mean()), res

    @staticmethod
    def _peak(rho, i):
        if 0 < i < len(rho) - 1:
            y0, y1, y2 = abs(rho[i - 1]), abs(rho[i]), abs(rho[i + 1])
            den = y0 - 2 * y1 + y2
            if den < 0:
                return i + 0.5 * (y0 - y2) / den
        return float(i)

    # -- main entry
    def process(self, x):
        x = _resample(x, self.fs, FS)
        y = np.convolve(x, _RRC)[_RRC_D:_RRC_D + len(x)]
        rho = self._rho(y)
        ar = np.abs(rho)
        cand = np.where((ar > self.hunt_rho) &
                        (ar >= np.maximum.reduce([np.roll(ar, k) for k in range(-5, 6)])))[0]
        frames = []
        nominal = ysf.FRAME_SYMS * SPS
        i_c = 0
        t = None
        sps = float(SPS)
        miss = 0
        prior = None
        while True:
            if t is None:                                   # hunting
                found = False
                while i_c < len(cand):
                    c = cand[i_c]
                    i_c += 1
                    if frames and c < frames[-1].start + nominal - self.search:
                        continue
                    tp = self._peak(rho, c)
                    out = self._frame(y, tp, sps)
                    if out is None:
                        continue
                    llr, a, snr = out
                    fich = ysf.FICH.decode(llr[ysf.SYNC_BITS:ysf.PAYLOAD_OFFSET])
                    if fich is not None:
                        frames.append(RxFrame(tp, rho[c], llr, fich, a, snr))
                        t, miss, sps, prior = tp, 0, float(SPS), a
                        found = True
                        break
                if not found:
                    break
                if frames[-1].fich.fi == ysf.FI_TERMINATOR:
                    t = None
                continue
            # locked: look for the next sync near the predicted position
            pred = t + ysf.FRAME_SYMS * sps
            lo, hi = int(pred) - self.search, int(pred) + self.search + 1
            if hi + nominal // 8 >= len(y):
                break
            j = lo + int(np.argmax(ar[lo:hi]))
            # Re-time only on a sync peak that is clearly real; in a fade, keep the flywheel.
            tries = [(self._peak(rho, j), True), (pred, False)] if ar[j] > 0.5 else [(pred, False)]
            best = None
            for tp, at_peak in tries:
                out = self._frame(y, tp, sps, prior)
                if out is None:
                    continue
                fich = ysf.FICH.decode(out[0][ysf.SYNC_BITS:ysf.PAYLOAD_OFFSET])
                if best is None or (fich is not None and best[2] is None):
                    best = (tp, out, fich, at_peak)
                if fich is not None:
                    break
            if best is None:
                break
            tp, (llr, a, snr), fich, at_peak = best
            if at_peak and fich is None and ar[j] < 0.85:
                tp = pred
                llr, a, snr = self._frame(y, tp, sps, prior)
            strong = ar[j] > 0.5
            frames.append(RxFrame(tp, rho[j], llr, fich, a, snr))
            if fich is not None:
                prior = a
            if strong and fich is not None:
                sps = 0.8 * sps + 0.2 * (tp - t) / ysf.FRAME_SYMS
                sps = float(np.clip(sps, SPS * 0.995, SPS * 1.005))
            miss = 0 if (strong or fich is not None) else miss + 1
            t = tp
            if (fich is not None and fich.fi == ysf.FI_TERMINATOR) or miss >= self.max_miss:
                t = None
                while i_c < len(cand) and cand[i_c] < tp + nominal - self.search:
                    i_c += 1
        return frames
