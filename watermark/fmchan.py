"""Narrowband FM voice channel, simplex or through a repeater, simulated at complex baseband.

One hop: pre-emphasis (750 us), mic gain, a hard deviation limiter, a 3 kHz splatter filter,
an optional CTCSS tone, FM at 2.5 kHz peak deviation, white noise at a given carrier-to-noise
ratio in the 12.5 kHz channel, an IF filter, a discriminator, de-emphasis and the receiver's
300-3000 Hz voice filter (the CTCSS high-pass). A repeater is two hops: its receiver's audio
(de-emphasised and filtered, as a cheap repeater does) is re-emphasised, limited again and sent
on the output frequency. Audio in and out is 8 kHz float, speech near -26 dBFS.
"""
import numpy as np
from scipy import signal

FS_AUDIO = 8000
FS_RF = 48000
DEV = 2500.0          # Hz peak deviation at the limiter
TAU = 750e-6          # pre/de-emphasis time constant


def _emph(fs, pre):
    """First-order 750 us pre-emphasis (shelved at 3.4 kHz so it stays bounded) or its inverse."""
    w1, w2 = 1 / TAU, 2 * np.pi * 3400
    num, den = [1 / w1, 1], [1 / w2, 1]
    if not pre:
        num, den = den, num
    b, a = signal.bilinear(num, den, fs)
    # unity gain at 1 kHz
    _, h = signal.freqz(b, a, [1000], fs=fs)
    return b / abs(h[0]), a


def _voice_bp(fs, order=6):
    return signal.butter(order, [300, 3000], "bandpass", fs=fs, output="sos")


def tx_audio(x, drive_db=0.0, fs=FS_AUDIO):
    """Mic audio -> limited, filtered modulating signal in units of peak deviation.
    drive_db 0 puts speech peaks near the limiter; +6 is a loud talker who clips often."""
    b, a = _emph(fs, True)
    y = signal.lfilter(b, a, x)
    # speech near -26 dBFS: scale so its 99th-percentile peak sits at the limiter
    ref = np.percentile(np.abs(y), 99.5) + 1e-9
    y = y / ref * 10 ** (drive_db / 20)
    clipped = np.mean(np.abs(y) > 1)
    y = np.clip(y, -1, 1)
    y = signal.sosfilt(signal.butter(6, 3000, "low", fs=fs, output="sos"), y)
    y = signal.sosfilt(signal.butter(2, 250, "high", fs=fs, output="sos"), y)
    return y, clipped


def fm_hop(m, cnr_db, ctcss=None, rng=None, fs=FS_AUDIO):
    """Modulating signal (units of peak deviation, fs) -> discriminator audio (fs), de-emphasised
    and voice-filtered. cnr_db is carrier to noise in 12.5 kHz; None means no noise."""
    rng = rng or np.random.default_rng(0)
    up = FS_RF // fs
    mu = signal.resample_poly(m, up, 1)
    t = np.arange(len(mu)) / FS_RF
    dev = mu * DEV
    if ctcss:
        dev = dev + 0.12 * DEV * np.sin(2 * np.pi * ctcss * t)
    ph = 2 * np.pi * np.cumsum(dev) / FS_RF
    s = np.exp(1j * ph)
    if cnr_db is not None:
        # noise power in 12.5 kHz = 1 / cnr; white across FS_RF
        npow = 10 ** (-cnr_db / 10) * FS_RF / 12500
        s = s + np.sqrt(npow / 2) * (rng.standard_normal(len(s)) + 1j * rng.standard_normal(len(s)))
    s = signal.sosfiltfilt(signal.butter(5, 5500, "low", fs=FS_RF, output="sos"), s)
    d = np.angle(s[1:] * np.conj(s[:-1])) * FS_RF / (2 * np.pi) / DEV
    d = np.concatenate([[0.0], d])
    d = signal.resample_poly(d, 1, up)[:len(m)]
    b, a = _emph(fs, False)
    d = signal.lfilter(b, a, d)
    return signal.sosfilt(_voice_bp(fs), d)


def channel(x, kind="repeater", cnr_in=30.0, cnr_out=30.0, drive_db=0.0, ctcss=100.0, seed=0):
    """Speech (8 kHz) -> what a listener's radio plays (8 kHz, same level as x).
    kind: "clean" (passthrough), "bandpass" (300-3000 Hz only), "simplex" (one hop, cnr_in),
    "repeater" (user -> repeater at cnr_in, repeater -> listener at cnr_out)."""
    rng = np.random.default_rng(seed)
    if kind == "clean":
        return x.copy(), {}
    if kind == "bandpass":
        return signal.sosfilt(_voice_bp(FS_AUDIO), x), {}
    lvl = np.sqrt(np.mean(x ** 2)) + 1e-12
    m, c1 = tx_audio(x, drive_db)
    y = fm_hop(m, cnr_in, ctcss, rng)
    info = {"clipped_tx": c1}
    if kind == "repeater":
        # repeater: received audio re-emphasised and limited onto the output carrier; it
        # regenerates its own CTCSS
        m2, c2 = tx_audio(y, drive_db=0.0)
        info["clipped_rpt"] = c2
        y = fm_hop(m2, cnr_out, ctcss, rng)
    y = y * lvl / (np.sqrt(np.mean(y ** 2)) + 1e-12)
    return y, info
