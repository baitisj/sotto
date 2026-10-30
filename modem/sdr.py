"""Complex baseband (IQ) helpers for SDR use: FM-modulate the modem's baseband, and
channel-filter + discriminate received IQ back to baseband."""
import numpy as np
from scipy import signal

from . import c4fm


def fm_modulate(freq_hz, fs_in=c4fm.FS, fs_iq=240000):
    """Instantaneous frequency (Hz) at fs_in -> unit-amplitude complex64 IQ at fs_iq."""
    f = c4fm._resample(freq_hz, fs_in, fs_iq)
    return np.exp(2j * np.pi * np.cumsum(f) / fs_iq).astype(np.complex64)


def fm_demodulate(iq, fs_iq=240000, fs_out=c4fm.FS, bw_hz=6250.0):
    """Complex IQ at fs_iq -> discriminator output in Hz at fs_out."""
    h = signal.firwin(255, bw_hz, fs=fs_iq)
    x = signal.lfilter(h, 1.0, np.asarray(iq, np.complex64))
    d = np.angle(x[1:] * np.conj(x[:-1])) * fs_iq / (2 * np.pi)
    return c4fm._resample(np.concatenate([[0.0], d]), fs_iq, fs_out)
