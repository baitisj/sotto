"""C4FM (P25 / YSF-style) waveform simulator with lmr60-style two-path Rayleigh fading.

Signal chain (complex baseband, FS = 48 kHz, 10 samples/symbol):
  dibits -> levels {+3,+1,-1,-3} -> raised-cosine (alpha 0.2) frequency pulse, 600 Hz/level
  -> FM -> two-path Rayleigh (independent paths, equal mean power, delay tau, Doppler fd)
  -> AWGN -> IF filter (+-6 kHz, per FTM-300 selectivity spec) -> discriminator
  -> post-detection LPF -> sample at symbol centre -> slicer + soft metrics.

Assumptions (optimistic): perfect symbol timing on path 1, no frequency offset, no
sync loss, no AGC/limiter dynamics. Our own code; no external codec/modem code used.
"""
import numpy as np
from scipy import signal

RS = 4800            # symbols/s
SPS = 10
FS = RS * SPS        # 48 kHz
DEV = 600.0          # Hz per level unit (+-600 / +-1800 Hz)
C = 3e8

# P25 / YSF Gray map: dibit (b0 b1) -> level
DIBIT_TO_LEVEL = {0b01: 3, 0b00: 1, 0b10: -1, 0b11: -3}
LEVELS = np.array([3, 1, -1, -3], dtype=float)
LEVEL_BITS = np.array([[0, 1], [0, 0], [1, 0], [1, 1]])  # rows match LEVELS


def bits_to_levels(bits):
    b = bits.reshape(-1, 2)
    idx = b[:, 0] * 2 + b[:, 1]
    lut = np.zeros(4)
    for k, v in DIBIT_TO_LEVEL.items():
        lut[k] = v
    return lut[idx]


def rc_pulse(alpha=0.2, span=8):
    t = np.arange(-span * SPS // 2, span * SPS // 2 + 1) / SPS
    h = np.sinc(t) * np.cos(np.pi * alpha * t)
    den = 1 - (2 * alpha * t) ** 2
    sing = np.abs(den) < 1e-8
    h[~sing] /= den[~sing]
    h[sing] = np.pi / 4 * np.sinc(1 / (2 * alpha))
    return h  # peak 1 at t=0, Nyquist zero crossings


_RC = rc_pulse()
_IF = signal.firwin(161, 6000, fs=FS)
_PD = signal.firwin(81, 3000, fs=FS)
# group delays (samples)
D_RC = (len(_RC) - 1) // 2
D_IF = (len(_IF) - 1) // 2
D_PD = (len(_PD) - 1) // 2


def doppler(band_hz, kmh):
    return kmh / 3.6 * band_hz / C


def rayleigh(n_sym, fd, rng, M=32):
    """Unit-power Rayleigh process at the symbol rate, sum of sinusoids (Jakes spectrum)."""
    t = np.arange(n_sym) / RS
    alpha = rng.uniform(-np.pi, np.pi, M)
    phi = rng.uniform(-np.pi, np.pi, M)
    h = np.zeros(n_sym, complex)
    for a, p in zip(alpha, phi):
        h += np.exp(1j * (2 * np.pi * fd * np.cos(a) * t + p))
    return h / np.sqrt(M)


def upsample_fading(h_sym, n):
    ts = np.arange(len(h_sym)) * SPS
    tt = np.arange(n)
    return np.interp(tt, ts, h_sym.real) + 1j * np.interp(tt, ts, h_sym.imag)


def simulate(levels, ebn0_db, fd=0.0, tau_s=0.0, two_path=True, seed=0, return_gain=False):
    """Run levels through the chain. Returns dict with sampled discriminator output (level units),
    per-symbol local gain |h|^2 (if fading) and noise sigma."""
    rng = np.random.default_rng(seed)
    n_sym = len(levels)
    imp = np.zeros(n_sym * SPS)
    imp[::SPS] = levels
    f = np.convolve(imp, _RC)[D_RC:D_RC + n_sym * SPS] * DEV          # instantaneous freq, Hz
    phase = 2 * np.pi * np.cumsum(f) / FS
    n = len(phase)
    s1 = np.exp(1j * phase)
    if fd > 0:
        h1 = upsample_fading(rayleigh(n_sym + 1, fd, rng), n)
        if two_path:
            h2 = upsample_fading(rayleigh(n_sym + 1, fd, rng), n)
            tt = np.arange(n) - tau_s * FS
            ph2 = np.interp(tt, np.arange(n), phase, left=0.0)
            s2 = np.exp(1j * ph2)
            x = (h1 * s1 + h2 * s2) / np.sqrt(2)
            gain = (np.abs(h1) ** 2 + np.abs(h2) ** 2) / 2
        else:
            x = h1 * s1
            gain = np.abs(h1) ** 2
    else:
        x = s1
        gain = np.ones(n)
    # AWGN: mean signal power 1 -> Es = 1/RS, Eb = Es/2
    ebn0 = 10 ** (ebn0_db / 10)
    n0 = (1 / RS / 2) / ebn0
    sigma2 = n0 * FS
    x = x + np.sqrt(sigma2 / 2) * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    y = np.convolve(x, _IF)[D_IF:D_IF + n]
    d = np.angle(y[1:] * np.conj(y[:-1])) * FS / (2 * np.pi)
    d = np.concatenate([[0.0], d])
    d = np.convolve(d, _PD)[D_PD:D_PD + n]
    samp = d[::SPS] / DEV
    rssi = np.abs(y) ** 2
    out = {"y": samp,
           "gain": gain[::SPS],
           "rssi": rssi.reshape(n_sym, SPS).mean(1)}
    return out


def soft_demod(y, win=24, floor=0.05):
    """Hard dibits plus max-log bit LLRs using a locally estimated noise variance
    (sliding window of `win` symbols), so metrics shrink honestly in fades."""
    dist = (y[:, None] - LEVELS[None, :]) ** 2
    hard = np.argmin(dist, 1)
    resid = y - LEVELS[hard]
    k = np.ones(win) / win
    s2 = np.convolve(resid ** 2, k, mode="same") + floor
    llr = np.zeros((len(y), 2))
    for b in range(2):
        m0 = np.min(np.where(LEVEL_BITS[None, :, b] == 0, dist, np.inf), 1)
        m1 = np.min(np.where(LEVEL_BITS[None, :, b] == 1, dist, np.inf), 1)
        llr[:, b] = (m1 - m0) / (2 * s2)   # >0 means bit 0
    bits = LEVEL_BITS[hard].reshape(-1)
    return bits, llr.reshape(-1), s2
