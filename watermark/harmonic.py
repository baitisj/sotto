"""Pitch-locked harmonic phase watermark for FM voice.

The speaker's pitch (sotto's tracked4 tracker) gives the instantaneous phase Phi(t) of the
fundamental. Each harmonic k is heterodyned down, z_k(t) = LPF(x(t) e^{-j k Phi(t)}), so
z_k = (a_k / 2) e^{j psi_k}. Within a 3-harmonic triplet the second phase difference

    D_k = arg(z_{k+1} z_{k-1} / z_k^2) = psi_{k+1} - 2 psi_k + psi_{k-1}

does not depend on Phi at all: not on when the receiver starts, not on its pitch estimate
being a little off (an error rotates z_k at a rate proportional to k, which the second
difference cancels), and not on a pure delay in the channel. The embedder rotates each odd
harmonic k in the data band by the smallest Delta in (-pi/2, pi/2] that sets D_k to 0 (bit 0)
or pi (bit 1) for the 32 ms slot; even harmonics are left alone as the reference. The
receiver tracks the pitch of what it hears, computes D_k for the same odd harmonics, and
reads the bit as the sign of cos(D_k), weighted by the triplet's strength.

The data band is split into `nsub` sub-bands, each carrying its own bit per slot. Slots sit on
a fixed time grid; a slot that is not voiced carries nothing and the receiver treats it as an
erasure, so voicing disagreements never shift the bit stream.
"""
import os, sys
import numpy as np
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))

FS = 8000


class Params:
    slot = 256            # samples per slot (32 ms)
    band = (500.0, 2600.0)
    nsub = 4
    lpf = 30.0            # Hz, harmonic heterodyne low-pass
    ramp = 64             # samples, raised-cosine blend of Delta between slots
    strength = 1.0        # fraction of the full rotation (1 = set D exactly)
    fmin = 70.0

    def __init__(self, **kw):
        for k, v in kw.items():
            if not hasattr(self, k):
                raise KeyError(k)
            setattr(self, k, v)


def pitch_track(x):
    """8 kHz float speech -> (f0 Hz per sample, voiced flag per sample) from sotto's tracker."""
    import vocoder_lab as vl
    m = vl.analyse(np.asarray(x, float), "tracked4")
    f0 = m["Wo"] * FS / (2 * np.pi)
    v = m["voiced"] > 0
    tc = 80 * np.arange(len(m)) - 80          # frame centre (sample index), see sinusoid.spectra
    t = np.arange(len(x))
    if v.sum() < 2:
        return np.full(len(x), 120.0), np.zeros(len(x), bool)
    f = np.interp(t, tc[v], f0[v])
    vs = np.interp(t, tc, v.astype(float)) > 0.5
    return f, vs


def tx_track(x):
    """The pitch track the sender marks against: the track a receiver will get from the
    300-3000 Hz audio it hears (its fundamental is mostly gone), voiced only where that
    agrees within 5% with the track of the full-band speech. Marking against what the
    receiver will see, and only where the pitch is clear, roughly halves the bit errors that
    come from the two ends tracking differently (LibriSpeech 251 and 3536 through a
    noiseless repeater: 6-10% to 3.5%)."""
    f_full, v_full = pitch_track(x)
    sos = signal.butter(6, [300, 3000], "bandpass", fs=FS, output="sos")
    f_bp, v_bp = pitch_track(signal.sosfilt(sos, x))
    agree = v_full & v_bp & (np.abs(np.log(f_bp / f_full)) < 0.05)
    return f_bp, agree


def harmonics(x, f0, kmax, p):
    """z[k] for k = 0..kmax (row 0 unused): heterodyned, low-passed harmonic k."""
    phi = 2 * np.pi * np.cumsum(f0) / FS
    sos = signal.butter(2, p.lpf, "low", fs=FS, output="sos")
    Z = np.zeros((kmax + 2, len(x)), complex)
    for k in range(1, kmax + 2):
        Z[k] = signal.sosfiltfilt(sos, x * np.exp(-1j * k * phi))
    return Z, phi


def _slot_layout(n, f0, voiced, p, offset=0, gate="all"):
    """Per slot: core sample range, median f0, voiced flag (gate "all": every sample of the
    slot voiced, "core": the core voiced, "none": every slot). offset moves the grid."""
    ns = (n - max(offset, 0)) // p.slot
    out = []
    for j in range(ns):
        a, b = j * p.slot + offset, (j + 1) * p.slot + offset
        if a < 0:
            out.append((0, 0, p.fmin, False))
            continue
        c0, c1 = a + p.slot // 4, b - p.slot // 4
        v = {"all": voiced[a:b].all(), "core": voiced[c0:c1].all(), "none": True}[gate]
        out.append((c0, c1, max(float(np.median(f0[a:b])), p.fmin), bool(v)))
    return out


def _odd_in_band(f, p):
    """Odd harmonics k (k-1 >= 2) whose frequency k f falls in the data band, by sub-band."""
    lo, hi = p.band
    edges = np.geomspace(lo, hi, p.nsub + 1)
    subs = [[] for _ in range(p.nsub)]
    k = 3
    while k * f <= hi:
        if k * f >= lo:
            b = min(int(np.searchsorted(edges, k * f, "right")) - 1, p.nsub - 1)
            subs[b].append(k)
        k += 2
    return subs


def _triplet(Z, k, c0, c1):
    zp, z0, zm = Z[k + 1, c0:c1], Z[k, c0:c1], Z[k - 1, c0:c1]
    r = np.sum(zp * zm * np.conj(z0) ** 2)
    n = np.sum(np.abs(zp) * np.abs(zm) * np.abs(z0) ** 2) + 1e-30
    amp = np.mean(np.minimum(np.minimum(np.abs(zp), np.abs(zm)), np.abs(z0)))
    return r, n, amp


def embed(x, bits_for_slot, p=None, track=None):
    """Watermark x (8 kHz float). bits_for_slot(j) -> list of nsub bits (0/1) for slot j.
    Returns (y, info) with info["slots"] = embedded flags per slot."""
    p = p or Params()
    x = np.asarray(x, float)
    f0, voiced = track if track is not None else tx_track(x)
    kmax = int(p.band[1] / p.fmin) + 2
    Z, phi = harmonics(x, f0, kmax, p)
    lay = _slot_layout(len(x), f0, voiced, p)
    Delta = np.zeros((kmax + 2, len(x)))
    used = np.zeros(len(lay), bool)
    for j, (c0, c1, f, v) in enumerate(lay):
        if not v:
            continue
        bits = bits_for_slot(j)
        a, b = j * p.slot, (j + 1) * p.slot
        for sb, ks in enumerate(_odd_in_band(f, p)):
            th = np.pi * bits[sb]
            for k in ks:
                r, _, _ = _triplet(Z, k, c0, c1)
                d = np.angle(r)
                delta = np.angle(np.exp(1j * (d - th))) / 2      # in (-pi/2, pi/2]
                Delta[k, a:b] = p.strength * delta
                used[j] = True
    # blend between slots so the rotation never steps
    w = np.hanning(p.ramp + 2)[1:-1]
    w /= w.sum()
    y = x.copy()
    for k in range(3, kmax + 2, 2):
        if not Delta[k].any():
            continue
        dk = np.convolve(Delta[k], w, "same")
        y += 2 * np.real(Z[k] * (np.exp(1j * dk) - 1) * np.exp(1j * k * phi))
    return y, {"slots": used, "voiced_slots": np.array([l[3] for l in lay])}


class Receiver:
    """What a receiver computes once from the audio it hears: its own pitch track and the
    heterodyned harmonics. soft() then reads the slot grid at any timing offset."""

    def __init__(self, y, p=None, track=None, gate="all"):
        self.gate = gate
        self.p = p or Params()
        self.y = np.asarray(y, float)
        self.f0, self.voiced = track if track is not None else pitch_track(self.y)
        self.kmax = int(self.p.band[1] / self.p.fmin) + 2
        self.Z, _ = harmonics(self.y, self.f0, self.kmax, self.p)

    def triplets(self, offset=0):
        """Every (slot, sub-band, frequency, weighted unit phasor) the receiver reads."""
        p = self.p
        lay = _slot_layout(len(self.y), self.f0, self.voiced, p, offset, self.gate)
        rec = []
        for j, (c0, c1, f, v) in enumerate(lay):
            if not v:
                continue
            for sb, ks in enumerate(_odd_in_band(f, p)):
                for k in ks:
                    r, n, amp = _triplet(self.Z, k, c0, c1)
                    rec.append((j, sb, k * f, amp * r / n))
        return len(lay), rec

    def soft(self, offset=0, eq=None):
        """Complex soft values per (slot, sub-band); the bit is the sign of the real part once
        the channel's phase offset is removed. Unvoiced slots are 0. eq = (bin edges, phase
        per bin) removes the channel's phase bend first (see equalizer)."""
        n, rec = self.triplets(offset)
        S = np.zeros((n, self.p.nsub), complex)
        for j, sb, f, u in rec:
            if eq is not None:
                u = u * np.exp(-1j * eq[1][np.clip(np.searchsorted(eq[0], f) - 1, 0, len(eq[1]) - 1)])
            S[j, sb] += u
        return S

    def equalizer(self, offset, nbins=12):
        """Blind estimate of the channel's phase bend: the second phase difference a filter
        adds across three harmonics grows near the band edges (the 300 Hz high-pass most of
        all). Per frequency bin, the offset is half the angle of the summed squared phasors;
        the bins are unwrapped from the middle of the band so no bin flips polarity."""
        _, rec = self.triplets(offset)
        edges = np.geomspace(self.p.band[0], self.p.band[1], nbins + 1)
        acc = np.zeros(nbins, complex)
        for _, _, f, u in rec:
            acc[np.clip(np.searchsorted(edges, f) - 1, 0, nbins - 1)] += u * u
        two = np.angle(acc)
        mid = nbins // 2
        two[mid:] = np.unwrap(two[mid:])
        two[:mid + 1] = np.unwrap(two[:mid + 1][::-1])[::-1]
        return edges, two / 2

    def find_offset(self, span=None, step=8):
        """Blind slot timing: the grid offset whose soft values line up best as BPSK
        (|sum S^2| over sum |S|^2; an unmarked, natural phase pattern averages away)."""
        span = span or self.p.slot // 2
        best = None
        for off in range(-span, span, step):
            S = self.soft(off)
            m = np.abs(np.sum(S ** 2, axis=0)).sum() / (np.sum(np.abs(S) ** 2) + 1e-30)
            if best is None or m > best[0]:
                best = (m, off, S)
        return best[1], best[2], best[0]

    def read(self, equalize=True):
        """Timing, channel phase bend and polarity, all blind -> real soft values
        (slots x nsub, positive = bit 0) and a dict of what was estimated."""
        off, S, m = self.find_offset()
        info = {"offset": off, "timing_metric": m}
        if equalize:
            eq = self.equalizer(off)
            S = self.soft(off, eq)
            info["eq_deg"] = np.degrees(eq[1]).round(1).tolist()
        R, c = derotate(S)
        info["phase_deg"] = np.degrees(c).round(1).tolist()
        return R, info


def derotate(S):
    """Remove each sub-band's channel phase offset (estimated by squaring, taken in
    (-pi/2, pi/2]) and return real soft values (slots x nsub) and the offsets."""
    c = np.angle(np.sum(S ** 2, axis=0)) / 2
    return np.real(S * np.exp(-1j * c)[None, :]), c
