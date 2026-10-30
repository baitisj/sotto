"""Voice payload schemes: how five 48-bit vocoder frames (100 ms) fill one YSF frame.

  SottoVW  the sotto mode: VW (voice full-rate) layout, all 720 payload bits for voice.
           Each 48-bit frame gets a CRC-8 (5 x 56 = 280 bits), then a tail-biting K=7 code
           punctured to rate 7/18 -> 720 bits, spread over the whole 100 ms frame, then
           scrambled. FICH DT = voice FR, sotto flag set.
  DnRep    research baseline: Codec 2 in the DN (V/D mode 2) voice slots, protected the
           way Fusion protects AMBE: the first 27 bits sent three times, the rest bare.
  DnConv   research: the same DN slots (5 x 104 bits), CRC-8 per frame, tail-biting code
           punctured to rate 7/13.

decode() returns (bits (5, 48), good (5,), reliability (5,)). good is the CRC result (for
DnRep, a vote-disagreement threshold); reliability is the share of soft energy that
disagrees with the decision: ~0 for a clean frame, rising toward 0.5 for junk.
"""
import numpy as np

from . import fec, ysf

NF = 5
NB = 48


def pn9(n, seed=0x1FF):
    """x^9 + x^5 + 1 scrambling sequence."""
    s = seed
    out = np.zeros(n, np.int8)
    for i in range(n):
        out[i] = s & 1
        fb = (s ^ (s >> 4)) & 1
        s = (s >> 1) | (fb << 8)
    return out


def _spread(n, rows):
    """Permutation sending coded bit i to position (i % rows) * (n // rows) + i // rows."""
    i = np.arange(n)
    return (i % rows) * (n // rows) + i // rows


def _add_crc(frames):
    f = np.asarray(frames, np.int8).reshape(NF, NB)
    return np.concatenate([np.concatenate([x, fec.crc8(x)]) for x in f])


def _check_crc(u):
    u = u.reshape(NF, NB + 8)
    ok = np.array([(fec.crc8(x[:NB]) == x[NB:]).all() for x in u])
    return u[:, :NB], ok


def _frame_reliability(llr_coded, recoded, per):
    return np.array([fec.reliability(llr_coded[k * per:(k + 1) * per], recoded[k * per:(k + 1) * per])
                     for k in range(NF)])


class SottoVW:
    name = "sotto_vw"
    dt = ysf.DT_VOICE_FR
    sotto = True
    PERM = _spread(720, 24)
    PN = pn9(720)

    CODE = fec.RATE_7_18

    def encode(self, frames):
        c = self.CODE.encode(_add_crc(frames))
        out = np.zeros(720, np.int8)
        out[self.PERM] = c
        return out ^ self.PN

    def decode(self, llr):
        llr = np.where(self.PN == 1, -1.0, 1.0) * np.asarray(llr, float)
        c = llr[self.PERM]
        u = self.CODE.decode(c, NF * (NB + 8))
        rel = _frame_reliability(c, self.CODE.encode(u), 144)
        bits, ok = _check_crc(u)
        return bits, ok, rel


def _dn_vch_positions():
    return np.stack([k * 144 + 40 + np.arange(104) for k in range(NF)])


class _DN:
    dt = ysf.DT_VD_MODE2
    sotto = True
    VCH = _dn_vch_positions()
    DCH_FILL = pn9(720, seed=0x0A5)

    def _place(self, vch5):
        out = self.DCH_FILL.copy()
        for k in range(NF):
            out[self.VCH[k]] = vch5[k]
        return out


class DnRep(_DN):
    """Fusion-style: 27 bits x 3 + 21 bits + 2 pad = 104 bits per 20 ms, whitened, interleaved."""
    name = "dn_rep"
    W = ysf.WHITENING[:104]
    GOOD_REL = 0.02            # share of triplet soft energy outvoted

    def encode(self, frames):
        vch5 = []
        for f in np.asarray(frames, np.int8):
            v = np.concatenate([np.repeat(f[:27], 3), f[27:], [0, 0]]).astype(np.int8) ^ self.W
            tx = np.zeros(104, np.int8)
            tx[ysf.IL_VCH] = v
            vch5.append(tx)
        return self._place(vch5)

    def decode(self, llr):
        llr = np.asarray(llr, float)
        bits, rel = [], []
        for k in range(NF):
            v = llr[self.VCH[k]][ysf.IL_VCH] * np.where(self.W == 1, -1.0, 1.0)
            trip = v[:81].reshape(27, 3)
            s = trip.sum(1)
            b = np.concatenate([(s < 0), (v[81:102] < 0)]).astype(np.int8)
            bits.append(b)
            rel.append(fec.reliability(trip.reshape(-1), np.repeat(b[:27], 3)))
        rel = np.array(rel)
        return np.array(bits), rel < self.GOOD_REL, rel


class DnConv(_DN):
    name = "dn_conv"
    PERM = _spread(520, 20)
    PN = pn9(520)
    CODE = fec.RATE_7_13

    def encode(self, frames):
        c = self.CODE.encode(_add_crc(frames))
        tx = np.zeros(520, np.int8)
        tx[self.PERM] = c
        tx ^= self.PN
        return self._place(tx.reshape(NF, 104))

    def decode(self, llr):
        llr = np.asarray(llr, float)
        v = np.concatenate([llr[self.VCH[k]] for k in range(NF)]) * np.where(self.PN == 1, -1.0, 1.0)
        c = v[self.PERM]
        u = self.CODE.decode(c, NF * (NB + 8))
        rel = _frame_reliability(c, self.CODE.encode(u), 104)
        bits, ok = _check_crc(u)
        return bits, ok, rel


SCHEMES = {s.name: s for s in (SottoVW(), DnRep(), DnConv())}
