"""Vocoder frames <-> YSF frames <-> baseband audio, with simple frame concealment."""
import numpy as np

from . import c4fm, ysf
from .payload import NB, NF, SCHEMES

# Codec 2 2400 frame that decodes to near silence: unvoiced, Wo/E index 26, LSP indexes 0
CODEC2_2400_MUTE = np.zeros(NB, np.int8)
CODEC2_2400_MUTE[2:10] = [(26 >> (7 - i)) & 1 for i in range(8)]


class Transmitter:
    def __init__(self, scheme="sotto_vw", dest="CQCQCQ", src="N0CALL", dgid=0, fs=c4fm.FS):
        self.scheme = SCHEMES[scheme]
        self.dest, self.src, self.dgid = dest, src, dgid
        self.mod = c4fm.Modulator(fs)

    def _fich(self, fi, fn=0):
        return ysf.FICH(fi=fi, fn=fn, ft=6, dt=self.scheme.dt, dgid=self.dgid, sotto=self.scheme.sotto)

    def frames(self, codec_frames):
        """codec_frames: (n, 48) bits -> list of 960-bit YSF frames (header, voice, terminator)."""
        cf = np.asarray(codec_frames, np.int8).reshape(-1, NB)
        pad = (-len(cf)) % NF
        if pad:
            cf = np.concatenate([cf, np.repeat(cf[-1:], pad, 0)])
        hdr = ysf.header_payload(self.dest, self.src)
        out = [ysf.build_frame(self._fich(ysf.FI_HEADER), hdr)]
        for i in range(len(cf) // NF):
            out.append(ysf.build_frame(self._fich(ysf.FI_COMMS, i % 7),
                                       self.scheme.encode(cf[i * NF:(i + 1) * NF])))
        out.append(ysf.build_frame(self._fich(ysf.FI_TERMINATOR), hdr))
        return out

    def modulate(self, codec_frames):
        """-> instantaneous frequency in Hz (sample rate self.mod.fs)."""
        return self.mod.modulate(np.concatenate(self.frames(codec_frames)))


class Receiver:
    """Audio -> vocoder frames. Bad frames (CRC failure) are replaced by the last good one,
    repeated at most max_repeat times, then by the mute frame."""

    def __init__(self, scheme="sotto_vw", fs=c4fm.FS, max_repeat=3, mute=None):
        self.scheme = SCHEMES[scheme]
        self.demod = c4fm.Demodulator(fs)
        self.max_repeat = max_repeat
        self.mute = CODEC2_2400_MUTE if mute is None else np.asarray(mute, np.int8)

    def receive(self, audio, conceal=True, t0=None):
        """Returns dict with 'frames' (n, 48), 'raw_frames', 'reliability' (n,), 'header',
        'rx_frames' and 't0'. Codec frames are placed by time: YSF frame k is the one that
        starts k*100 ms after t0 (the first voice frame's start, in 48 kHz samples, unless
        given). Missing frames come out as erasures."""
        rx = self.demod.process(audio)
        header = None
        voice = []
        for f in rx:
            _, pay = ysf.split_frame(f.llr)
            if f.fich is not None and f.fich.fi in (ysf.FI_HEADER, ysf.FI_TERMINATOR):
                if header is None and f.fich.fi == ysf.FI_HEADER:
                    header = ysf.decode_header_payload(pay)
                continue
            if f.fich is not None and f.fich.dt != self.scheme.dt:
                continue
            if f.fich is None and not voice:
                continue
            b, g, r = self.scheme.decode(pay)
            voice.append((f.start, b, g, r))
        if not voice:
            return {"frames": np.zeros((0, NB), np.int8), "raw_frames": np.zeros((0, NB), np.int8),
                    "good": np.zeros(0, bool), "reliability": np.zeros(0), "header": header,
                    "rx_frames": rx, "t0": t0}
        if t0 is None:
            t0 = voice[0][0]
        period = ysf.FRAME_SYMS * c4fm.SPS
        slots = {}
        for start, b, g, r in voice:
            k = int(round((start - t0) / period))
            if k >= 0 and k not in slots:
                slots[k] = (b, g, r)
        n = max(slots) + 1 if slots else 0
        bits = np.zeros((n * NF, NB), np.int8)
        good = np.zeros(n * NF, bool)
        rel = np.full(n * NF, 0.5)
        for k, (b, g, r) in slots.items():
            bits[k * NF:(k + 1) * NF] = b
            good[k * NF:(k + 1) * NF] = g
            rel[k * NF:(k + 1) * NF] = r
        out = bits.copy()
        if conceal:
            last, rep = self.mute, 0
            for i in range(len(out)):
                if not good[i]:
                    rep += 1
                    out[i] = last if rep <= self.max_repeat else self.mute
                else:
                    last, rep = out[i], 0
        return {"frames": out, "raw_frames": bits, "good": good, "reliability": rel,
                "header": header, "rx_frames": rx, "t0": t0}
