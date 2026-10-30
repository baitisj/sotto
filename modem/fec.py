"""Tail-biting K=7 convolutional code (133, 171, 165 octal), rate 1/3, optional puncturing.

Tail-biting lets one YSF frame (5 x 48 = 240 info bits) fill exactly 720 coded bits with
no tail overhead. Decoding uses the wrap-around Viterbi trick: the soft input is extended
circularly on both sides, decoded with a free start state, and the middle is kept.
"""
import numpy as np

G = (0o133, 0o171, 0o165)
K = 7
NS = 1 << (K - 1)


def _parity(x):
    return np.array([bin(int(v)).count("1") & 1 for v in np.ravel(x)]).reshape(np.shape(x))


def encode(u):
    """Tail-biting encode. u: info bits (len n). Returns (n, 3) coded bits."""
    u = np.asarray(u, np.int8)
    n = len(u)
    reg = 0
    for b in u[-(K - 1):]:              # preload the register with the last K-1 bits
        reg = ((reg << 1) | int(b)) & (2 * NS - 1)
    out = np.zeros((n, 3), np.int8)
    for i, b in enumerate(u):
        reg = ((reg << 1) | int(b)) & (2 * NS - 1)
        for j, g in enumerate(G):
            out[i, j] = bin(reg & g).count("1") & 1
    return out


_n = np.arange(NS)
_PRED = np.stack([_n >> 1, (_n >> 1) | (NS >> 1)])          # predecessor states for each state
_REG = ((_PRED << 1) | (_n & 1)) & (2 * NS - 1)
_SGN = np.stack([1 - 2 * _parity(_REG & g) for g in G]).astype(float)   # (3, 2, NS)


def _viterbi(llr3):
    n = len(llr3)
    pm = np.zeros(NS)
    dec = np.zeros((n, NS), np.int8)
    for i in range(n):
        cand = pm[_PRED] + np.tensordot(llr3[i], _SGN, 1)
        ch = cand[1] > cand[0]
        dec[i] = ch
        pm = np.where(ch, cand[1], cand[0])
        pm -= pm.max()
    s = int(np.argmax(pm))
    out = np.zeros(n, np.int8)
    for i in range(n - 1, -1, -1):
        out[i] = s & 1
        s = int(_PRED[dec[i, s], s])
    return out


def decode(llr3, wrap=48):
    """llr3: (n, 3) soft values (positive = bit 0; 0 = punctured). Returns n info bits."""
    llr3 = np.asarray(llr3, float)
    n = len(llr3)
    w = min(wrap, n)
    ext = np.concatenate([llr3[-w:], llr3, llr3[:w]])
    return _viterbi(ext)[w:w + n]


class Punctured:
    """Rate-1/3 mother code punctured by a periodic keep-mask of shape (period, 3)."""

    def __init__(self, keep):
        self.keep = np.asarray(keep, bool)

    def _mask(self, n):
        reps = -(-n // len(self.keep))
        return np.tile(self.keep, (reps, 1))[:n]

    def n_coded(self, n):
        return int(self._mask(n).sum())

    def encode(self, u):
        c = encode(u)
        return c[self._mask(len(u))]

    def decode(self, llr, n):
        m = self._mask(n)
        full = np.zeros((n, 3))
        full[m] = llr
        return decode(full)


RATE_1_3 = Punctured(np.ones((1, 3), bool))


def reliability(llr, recoded):
    """Fraction of soft energy that disagrees with the re-encoded decision (0 good, ~0.5 bad)."""
    llr = np.asarray(llr, float)
    a = np.abs(llr)
    bad = ((llr < 0).astype(np.int8) != recoded)
    return float((a * bad).sum() / (a.sum() + 1e-12))


def crc8(bits, poly=0x07):
    """CRC-8 (x^8 + x^2 + x + 1, init 0) over a bit array; returns 8 bits, MSB first."""
    c = 0
    for b in np.asarray(bits, np.int8):
        fb = ((c >> 7) & 1) ^ int(b)
        c = ((c << 1) & 0xFF) ^ (poly if fb else 0)
    return np.array([(c >> (7 - i)) & 1 for i in range(8)], np.int8)


# 7 info bits -> 18 coded bits (rate 7/18): all g1 and g2 bits, g3 on alternate bits
RATE_7_18 = Punctured(np.array([[1, 1, 1], [1, 1, 0]] * 3 + [[1, 1, 1]], bool))
# 7 info bits -> 13 coded bits (rate 7/13): all g1 bits, six of seven g2 bits, no g3
RATE_7_13 = Punctured(np.array([[1, 1, 0]] * 6 + [[1, 0, 0]], bool))
