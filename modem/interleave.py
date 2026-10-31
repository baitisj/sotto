"""Depth-2 interleaving for the sotto VW payload: each 100 ms codeword (five vocoder frames,
720 coded bits) is split between two consecutive YSF frames, so a fade that wipes out
one YSF frame costs each of two codewords half its bits instead of one codeword all of
them. Even payload positions of YSF frame k carry codeword k, odd positions carry
codeword k-1. One extra voice frame at the end carries the last codeword's second half.
Adds 100 ms of delay.
"""
import numpy as np

from . import c4fm, ysf
from .link import Transmitter, Receiver
from .payload import NB, NF

EVEN = np.arange(720) % 2 == 0


class Transmitter2(Transmitter):
    def frames(self, codec_frames):
        cf = np.asarray(codec_frames, np.int8).reshape(-1, NB)
        pad = (-len(cf)) % NF
        if pad:
            cf = np.concatenate([cf, np.repeat(cf[-1:], pad, 0)])
        words = [self.scheme.encode(cf[i * NF:(i + 1) * NF]) for i in range(len(cf) // NF)]
        filler = self.scheme.encode(np.repeat(cf[-1:], NF, 0))
        hdr = ysf.header_payload(self.dest, self.src)
        out = [ysf.build_frame(self._fich(ysf.FI_HEADER), hdr)]
        for i in range(len(words) + 1):
            cur = words[i] if i < len(words) else filler
            prev = words[i - 1] if i > 0 else filler
            out.append(ysf.build_frame(self._fich(ysf.FI_COMMS, i % 7), np.where(EVEN, cur, prev)))
        out.append(ysf.build_frame(self._fich(ysf.FI_TERMINATOR), hdr))
        return out


class Receiver2(Receiver):
    def receive(self, audio, conceal=True, t0=None):
        rx = self.demod.process(audio)
        voice = []
        for f in rx:
            _, pay = ysf.split_frame(f.llr)
            if f.fich is not None and f.fich.fi in (ysf.FI_HEADER, ysf.FI_TERMINATOR):
                continue
            if f.fich is not None and f.fich.dt != self.scheme.dt:
                continue
            if f.fich is None and not voice:
                continue
            voice.append((f.start, np.asarray(pay, float)))
        if not voice:
            return {"frames": np.zeros((0, NB), np.int8), "good": np.zeros(0, bool), "t0": t0}
        if t0 is None:
            t0 = voice[0][0]
        period = ysf.FRAME_SYMS * c4fm.SPS
        slots = {}
        for start, pay in voice:
            k = int(round((start - t0) / period))
            if k >= 0 and k not in slots:
                slots[k] = pay
        n = max(slots) if slots else 0          # the last slot only carries a second half
        bits = np.zeros((n * NF, NB), np.int8)
        good = np.zeros(n * NF, bool)
        zero = np.zeros(720)
        for k in range(n):
            a, b = slots.get(k, zero), slots.get(k + 1, zero)
            llr = np.where(EVEN, a, b)
            bk, gk, _ = self.scheme.decode(llr)
            bits[k * NF:(k + 1) * NF] = bk
            good[k * NF:(k + 1) * NF] = gk
        out = bits.copy()
        if conceal:
            last, rep = self.mute, 0
            for i in range(len(out)):
                if not good[i]:
                    rep += 1
                    out[i] = last if rep <= self.max_repeat else self.mute
                else:
                    last, rep = out[i], 0
        return {"frames": out, "raw_frames": bits, "good": good, "t0": t0}
