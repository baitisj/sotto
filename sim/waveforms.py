"""Candidate baseband-over-FM waveforms for a 3600 bps voice channel.

The FTM-300's DSP can only drive the FM VCO (DSP_MODOUT -> VCOMOD) and only hears the
FM discriminator (DISCA/DISCB), so every waveform here is a baseband frequency signal f(t)
that goes through the same FM -> fading -> AWGN -> IF filter -> discriminator chain.
Noise is set by C/N0 (dB-Hz) with unit RF power, so waveforms with different symbol
rates are compared at equal transmitted power and equal information rate.

Waveforms (all carry 3600 bps of coded voice):
  c4fm_dn   C4FM 4800 baud, voice in 36 of every 96 symbols (Fusion DN-style slot)
  fsk4_1800 4FSK 1800 baud, +-600/+-1800 Hz, RC alpha 0.2, discriminator
  fsk2_3600 2FSK 3600 baud, +-1800 Hz, RC alpha 0.2, discriminator
  ofdm      40-carrier DQPSK OFDM in the audio band (400-2350 Hz, 50 Hz spacing,
            20 ms + 2 ms CP), FM-modulated with 1 kHz rms deviation, clipped at 2.8 kHz
"""
import numpy as np
from scipy import signal
import c4fm_sim as cs

FS = cs.FS
_IF_CACHE = {}


def _if_filter(fs):
    if fs not in _IF_CACHE:
        _IF_CACHE[fs] = signal.firwin(161, 6000, fs=fs)
    return _IF_CACHE[fs]


def _fading(n, fs, fd, rng, decim=10):
    """Rayleigh process generated at fs/decim and linearly interpolated to fs."""
    m = n // decim + 2
    t = np.arange(m) * decim / fs
    M = 32
    a = rng.uniform(-np.pi, np.pi, M)
    p = rng.uniform(-np.pi, np.pi, M)
    h = np.exp(1j * (2 * np.pi * fd * np.cos(a)[None, :] * t[:, None] + p[None, :])).sum(1) / np.sqrt(M)
    tt = np.arange(n)
    ts = np.arange(m) * decim
    return np.interp(tt, ts, h.real) + 1j * np.interp(tt, ts, h.imag)


def fm_channel(freq, cn0_db, fd=0.0, tau_s=0.0, two_path=False, seed=0, fs=FS):
    """freq: instantaneous frequency (Hz) at fs. Returns discriminator output (Hz) and
    per-sample RF power gain."""
    rng = np.random.default_rng(seed)
    n = len(freq)
    phase = 2 * np.pi * np.cumsum(freq) / fs
    s1 = np.exp(1j * phase)
    if fd > 0:
        h1 = _fading(n, fs, fd, rng)
        if two_path:
            h2 = _fading(n, fs, fd, rng)
            ph2 = np.interp(np.arange(n) - tau_s * fs, np.arange(n), phase, left=0.0)
            x = (h1 * s1 + h2 * np.exp(1j * ph2)) / np.sqrt(2)
            gain = (np.abs(h1) ** 2 + np.abs(h2) ** 2) / 2
        else:
            x = h1 * s1
            gain = np.abs(h1) ** 2
    else:
        x = s1
        gain = np.ones(n)
    sigma2 = fs / 10 ** (cn0_db / 10)
    x = x + np.sqrt(sigma2 / 2) * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    h = _if_filter(fs)
    d0 = (len(h) - 1) // 2
    y = np.convolve(x, h)[d0:d0 + n]
    d = np.angle(y[1:] * np.conj(y[:-1])) * fs / (2 * np.pi)
    return np.concatenate([[0.0], d]), gain


# ---------------------------------------------------------------- FSK family
def _rc(alpha, sps, span=8):
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    h = np.sinc(t) * np.cos(np.pi * alpha * t)
    den = 1 - (2 * alpha * t) ** 2
    sing = np.abs(den) < 1e-8
    h[~sing] /= den[~sing]
    h[sing] = np.pi / 4 * np.sinc(1 / (2 * alpha))
    return h


class FSK:
    def __init__(self, name, baud, levels_hz, bits_per_sym, lpf_hz, voice_frac=1.0, fs=FS):
        self.name, self.baud, self.fs = name, baud, fs
        self.sps = fs // baud
        assert self.sps * baud == fs
        self.levels = np.asarray(levels_hz, float)
        self.k = bits_per_sym
        self.pulse = _rc(0.2, self.sps)
        self.lpf = signal.firwin(81, lpf_hz, fs=fs)
        self.voice_frac = voice_frac

    # Gray maps
    def bits_to_sym(self, bits):
        if self.k == 1:
            return np.where(bits == 0, 1.0, -1.0)
        return cs.bits_to_levels(bits) / 3.0          # +-1, +-1/3

    def modulate(self, bits):
        sym = self.bits_to_sym(bits)
        imp = np.zeros(len(sym) * self.sps)
        imp[::self.sps] = sym
        d = (len(self.pulse) - 1) // 2
        f = np.convolve(imp, self.pulse)[d:d + len(imp)]
        return f * self.levels.max(), len(sym)

    def demod(self, disc, n_sym, win=24, floor=0.003):
        d = (len(self.lpf) - 1) // 2
        z = np.convolve(disc, self.lpf)[d:d + len(disc)]
        y = z[::self.sps][:n_sym] / self.levels.max()
        if self.k == 1:
            hard = (y < 0).astype(np.int8)
            r = y - np.where(y >= 0, 1.0, -1.0)
            s2 = np.convolve(r ** 2, np.ones(win) / win, mode="same") + floor
            return hard, 2 * y / s2
        lv = cs.LEVELS / 3.0
        dist = (y[:, None] - lv[None, :]) ** 2
        h = np.argmin(dist, 1)
        s2 = np.convolve((y - lv[h]) ** 2, np.ones(win) / win, mode="same") + floor
        llr = np.zeros((n_sym, 2))
        for b in range(2):
            m0 = np.min(np.where(cs.LEVEL_BITS[None, :, b] == 0, dist, np.inf), 1)
            m1 = np.min(np.where(cs.LEVEL_BITS[None, :, b] == 1, dist, np.inf), 1)
            llr[:, b] = (m1 - m0) / (2 * s2)
        return cs.LEVEL_BITS[h].reshape(-1).astype(np.int8), llr.reshape(-1)


# ---------------------------------------------------------------- OFDM
class OFDM:
    name = "ofdm"

    def __init__(self, k0=8, nc=40, nfft=960, ncp=96, rms_hz=1000.0, clip_hz=2800.0):
        self.k0, self.nc, self.nfft, self.ncp = k0, nc, nfft, ncp
        self.rms, self.clip = rms_hz, clip_hz
        self.bps = 2 * nc                       # bits per OFDM symbol
        self.L = nfft + ncp

    def modulate(self, bits):
        nb = len(bits)
        nsym = -(-nb // self.bps)
        b = np.zeros(nsym * self.bps, np.int8)
        b[:nb] = bits
        b = b.reshape(nsym, self.nc, 2)
        q = np.array([[0, 1], [3, 2]])[b[..., 0], b[..., 1]]  # gray: 00->0 01->1 11->2 10->3
        ph = np.cumsum(np.pi / 2 * q, axis=0)
        ph = np.vstack([np.zeros((1, self.nc)), ph])          # reference symbol first
        X = np.zeros((nsym + 1, self.nfft), complex)
        X[:, self.k0:self.k0 + self.nc] = np.exp(1j * ph)
        x = np.fft.ifft(X, axis=1).real
        x = np.hstack([x[:, -self.ncp:], x]).reshape(-1)
        x *= self.rms / np.sqrt(np.mean(x ** 2))
        x = np.clip(x, -self.clip, self.clip)
        lead = int(0.05 * FS)                                  # 50 ms settle
        return np.concatenate([np.zeros(lead), x, np.zeros(lead)]), (nsym, lead, nb)

    def demod(self, disc, meta):
        nsym, lead, nb = meta
        seg = disc[lead:lead + (nsym + 1) * self.L].reshape(nsym + 1, self.L)[:, self.ncp:]
        Y = np.fft.fft(seg, axis=1)[:, self.k0:self.k0 + self.nc]
        z = Y[1:] * np.conj(Y[:-1]) * np.exp(1j * np.pi / 4)
        a = np.abs(z)
        # ideal points at 45-degree diagonals with the measured magnitude
        pts = (np.sign(z.real) + 1j * np.sign(z.imag)) / np.sqrt(2) * a
        e = np.abs(z - pts) ** 2
        g = e.reshape(nsym, 4, self.nc // 4).mean(2, keepdims=True)
        s2 = np.repeat(g, self.nc // 4, axis=2).reshape(nsym, self.nc) + 1e-9
        scale = a.reshape(nsym, 4, -1).mean(2, keepdims=True)
        scale = np.repeat(scale, self.nc // 4, axis=2).reshape(nsym, self.nc)
        l0 = 2 * scale * z.imag / s2        # b0: + imag -> 0
        l1 = 2 * scale * z.real / s2        # b1: + real -> 0
        llr = np.stack([l0, l1], -1).reshape(-1)[:nb]
        hard = (llr < 0).astype(np.int8)
        return hard, llr
