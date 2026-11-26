"""Message coding for the harmonic watermark: a 56-bit ID frame (callsign, a "tone" code, CRC-16)
under a K=7 rate-1/2 convolutional code, sent over and over on the slot grid. Each pass of the
codeword is spread over the slots by a stride permutation, so a pause erases scattered coded
bits rather than a run of them, and the receiver adds up every pass it has heard before it
runs the soft Viterbi decoder.
"""
import numpy as np

G = (0o171, 0o133)
K = 7
NSTATE = 1 << (K - 1)
ALPHABET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/."     # M17-style base-40


def pack_call(call):
    v = 0
    for ch in reversed(call.upper()[:6]):
        v = v * 40 + ALPHABET.index(ch)
    return v


def unpack_call(v):
    s = ""
    while v:
        s += ALPHABET[v % 40]
        v //= 40
    return s


def crc16(bits):
    """CRC-16/CCITT-FALSE over a bit list, MSB first."""
    r = 0xFFFF
    for b in bits:
        top = (r >> 15) & 1
        r = (r << 1) & 0xFFFF
        if top ^ int(b):
            r ^= 0x1021
    return r


def _bits(v, n):
    return [(v >> (n - 1 - i)) & 1 for i in range(n)]


def _val(bits):
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def frame(call, code):
    """56 bits: 32-bit base-40 callsign, 8-bit code, CRC-16 over both."""
    b = _bits(pack_call(call), 32) + _bits(code & 0xFF, 8)
    return b + _bits(crc16(b), 16)


def unframe(b):
    """56 bits -> (call, code) or None when the CRC fails."""
    b = list(b)
    if crc16(b[:40]) != _val(b[40:56]):
        return None
    return unpack_call(_val(b[:32])), _val(b[32:40])


def _parity(v):
    return bin(v).count("1") & 1


# trellis: next state and outputs for (state, input)
_NEXT = np.zeros((NSTATE, 2), int)
_OUT = np.zeros((NSTATE, 2, 2), int)
for s in range(NSTATE):
    for u in range(2):
        reg = (u << (K - 1)) | s
        _NEXT[s, u] = reg >> 1
        _OUT[s, u] = [_parity(reg & g) for g in G]


def conv_encode(bits):
    s, out = 0, []
    for u in list(bits) + [0] * (K - 1):
        out += list(_OUT[s, u])
        s = _NEXT[s, u]
    return np.array(out, int)


# the two (state, input) pairs that lead into each state
_PRED = np.zeros((NSTATE, 2, 2), int)
_fill = np.zeros(NSTATE, int)
for s in range(NSTATE):
    for u in range(2):
        n = _NEXT[s, u]
        _PRED[n, _fill[n]] = (s, u)
        _fill[n] += 1


def viterbi(soft, nbits):
    """soft: coded-bit soft values, positive = 0, 0 = erased. Returns nbits decoded bits."""
    soft = np.asarray(soft, float).reshape(-1, 2)
    ps, pu = _PRED[:, :, 0], _PRED[:, :, 1]              # (NSTATE, 2)
    sign = 1 - 2 * _OUT[ps, pu]                          # (NSTATE, 2, 2): 0 -> +1, 1 -> -1
    pm = np.full(NSTATE, -1e18)
    pm[0] = 0.0
    hist = []
    for t in range(len(soft)):
        cand = pm[ps] + (sign * soft[t]).sum(2)
        c = cand.argmax(1)
        hist.append(c)
        pm = cand[np.arange(NSTATE), c]
    s, out = 0, []                                       # the tail ends in state 0
    for c in reversed(hist):
        i = c[s]
        out.append(pu[s, i])
        s = ps[s, i]
    return out[::-1][:nbits]


class Code:
    """The ID frame's codeword (124 coded bits) laid out over a slot grid of nsub bits per slot."""

    def __init__(self, call="AG7EW", code=0x5A, nsub=2, stride=37):
        self.msg = frame(call, code)
        self.n = 2 * (len(self.msg) + K - 1)
        # whitening: natural speech leans its phase pattern toward 0, which would otherwise
        # look like a run of zero bits and decode to frames near the all-zero codeword
        self.pn = np.random.default_rng(0x7E).integers(0, 2, self.n)
        self.cw = conv_encode(self.msg) ^ self.pn
        self.nsub = nsub
        assert np.gcd(stride, self.n) == 1
        self.perm = (np.arange(self.n) * stride) % self.n     # grid position -> coded bit

    def bits_for_slot(self, j, start=0):
        q = j * self.nsub + np.arange(self.nsub) + start
        return list(self.cw[self.perm[q % self.n]])

    def accumulate(self, R, start=0):
        """Real soft values (slots x nsub, positive = 0) -> summed soft value per coded bit."""
        acc = np.zeros(self.n)
        q = (np.arange(R.size) + start) % self.n
        np.add.at(acc, self.perm[q], R.reshape(-1))
        return acc * (1 - 2 * self.pn)               # de-whitened

    def quality(self, acc, bits):
        """How well the decoded frame's codeword agrees with the soft values (1 = every heard
        coded bit agrees; a frame Viterbi forces onto noise lands near 0.3-0.5) and the
        fraction of coded bits heard at all."""
        c = 1 - 2 * conv_encode(bits)
        return float(np.sum(acc * c) / (np.sum(np.abs(acc)) + 1e-30)), float(np.mean(acc != 0))

    def decode(self, R, search=True, polarity=False, qmin=0.9, cover=0.8):
        """Try every codeword start (the receiver doesn't know where the sender began), and with
        polarity set both signs of each sub-band; return (call, code, start, quality) for the
        first frame that passes the CRC with at least `cover` of its coded bits heard and a
        quality of at least qmin, or None."""
        starts = range(self.n) if search else [0]
        signs = [np.array([-1 if (m >> b) & 1 else 1 for b in range(self.nsub)])
                 for m in range((1 << self.nsub) if polarity else 1)]
        for sg in signs:
            Rs = R * sg[None, :]
            for st in starts:
                acc = self.accumulate(Rs, st)
                if np.mean(acc != 0) < cover:
                    continue
                bits = viterbi(acc, len(self.msg))
                got = unframe(bits)
                if got:
                    q, _ = self.quality(acc, bits)
                    self.last_q = q
                    if q >= qmin:
                        return got + (st, round(q, 3))
        return None
