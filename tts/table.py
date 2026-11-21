"""sotto-tts unit tables: the robotic phoneme table and the diphone table, as packed bits.

Both tables store speech frames the way sotto stores them: per 20 ms frame a 2-bit voicing
code, a 5-bit energy code and the spectral shape as indices into sotto v3.7's 9+9+8+8-bit
shape codebook (stages 1-2 only with shape_bits=18). Pitch is never stored: the synthesiser
sets it from its intonation rules, which is what makes the tables small.

Layout (all fields LSB-first in one bit stream):

    header   magic 'STT1', kind (0 robot, 1 diphone), shape bits (18 or 34),
             f0 (Hz), 42 x 2 duration bytes (stressed / unstressed, 5 ms units)
    robot    per phone: target count (3 bits), then that many frames
    diphone  a 42 x 42 presence bitmap, then per present pair (row-major): frame count
             (4 bits), the frame where the second phone starts (4 bits), the frames

SPDX-License-Identifier: MIT
"""
import numpy as np
from .phones import PHONES

NP = len(PHONES)
STAGE_BITS = (9, 9, 8, 8)


class BitWriter:
    def __init__(self):
        self.bits = []

    def put(self, v, n):
        v = int(v)
        assert 0 <= v < (1 << n), (v, n)
        self.bits += [(v >> k) & 1 for k in range(n)]

    def bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        a = np.array(b, np.uint8).reshape(-1, 8)
        return bytes((a << np.arange(8)).sum(1).astype(np.uint8))


class BitReader:
    def __init__(self, data):
        a = np.frombuffer(data, np.uint8)
        self.bits = ((a[:, None] >> np.arange(8)) & 1).ravel()
        self.p = 0

    def get(self, n):
        v = 0
        for k in range(n):
            v |= int(self.bits[self.p + k]) << k
        self.p += n
        return v


def put_frame(w, fr, shape_bits):
    w.put(fr["code"], 2)
    w.put(fr["ei"], 5)
    for k, b in enumerate(STAGE_BITS[:2 if shape_bits == 18 else 4]):
        w.put(fr["si"][k], b)


def get_frame(r, shape_bits):
    code = r.get(2)
    ei = r.get(5)
    si = [r.get(b) for b in STAGE_BITS[:2 if shape_bits == 18 else 4]]
    return dict(code=code, ei=ei, si=si)


def write(kind, shape_bits, f0, dur, units):
    """kind 'robot' (units: {phone: [frames]}) or 'diphone' (units: {(a, b): (split,
    [frames])}); dur: {phone: (stressed s, unstressed s)}. Returns bytes."""
    w = BitWriter()
    for c in b"STT1":
        w.put(c, 8)
    w.put(0 if kind == "robot" else 1, 8)
    w.put(shape_bits, 8)
    w.put(int(round(f0)), 16)
    for p in PHONES:
        a, b = dur.get(p, (0.08, 0.06))
        w.put(min(255, int(round(a / 0.005))), 8)
        w.put(min(255, int(round(b / 0.005))), 8)
    if kind == "robot":
        for p in PHONES:
            fr = units.get(p, [])
            w.put(len(fr), 3)
            for f in fr:
                put_frame(w, f, shape_bits)
    else:
        for a in PHONES:
            for b in PHONES:
                w.put(1 if (a, b) in units else 0, 1)
        for a in PHONES:
            for b in PHONES:
                if (a, b) in units:
                    split, fr = units[(a, b)]
                    assert 1 <= len(fr) <= 15 and 0 <= split <= len(fr)
                    w.put(len(fr), 4)
                    w.put(split, 4)
                    for f in fr:
                        put_frame(w, f, shape_bits)
    return w.bytes()


def read(data):
    r = BitReader(data)
    assert bytes(r.get(8) for _ in range(4)) == b"STT1"
    kind = "robot" if r.get(8) == 0 else "diphone"
    shape_bits = r.get(8)
    f0 = r.get(16)
    dur = {}
    for p in PHONES:
        dur[p] = (r.get(8) * 0.005, r.get(8) * 0.005)
    units = {}
    if kind == "robot":
        for p in PHONES:
            n = r.get(3)
            units[p] = [get_frame(r, shape_bits) for _ in range(n)]
    else:
        present = [(a, b) for a in PHONES for b in PHONES if r.get(1)]
        for pr in present:
            n = r.get(4)
            split = r.get(4)
            units[pr] = (split, [get_frame(r, shape_bits) for _ in range(n)])
    return dict(kind=kind, shape_bits=shape_bits, f0=f0, dur=dur, units=units)
