"""Yaesu System Fusion (YSF) air-interface framing, written from the public frame layout.

One YSF frame is 100 ms = 480 C4FM symbols = 960 bits:
  sync (40 bits) | FICH (200 bits) | payload (720 bits = 5 sections of 144 bits, 20 ms each)

The FICH carries 32 bits of frame information plus a CRC-16, protected by Golay(24,12),
a K=5 rate-1/2 convolutional code and a dibit interleaver. Header and terminator frames
carry two "CSD" fields (callsigns) with the same convolutional code. Voice payload
layouts depend on the data type (DT): V/D mode 2 ("DN") puts 40 data bits + 104 voice
bits in each section; voice full-rate ("VW") puts 144 voice bits in each section.

All bit arrays here are numpy int8 arrays of 0/1, most significant bit first.
"""
import numpy as np

SYNC_BYTES = bytes([0xD4, 0x71, 0xC9, 0x63, 0x4D])
FRAME_BITS = 960
FRAME_SYMS = 480
SYNC_BITS = 40
FICH_BITS = 200
PAYLOAD_BITS = 720
PAYLOAD_OFFSET = SYNC_BITS + FICH_BITS

FI_HEADER, FI_COMMS, FI_TERMINATOR, FI_TEST = 0, 1, 2, 3
DT_VD_MODE1, DT_DATA_FR, DT_VD_MODE2, DT_VOICE_FR = 0, 1, 2, 3

WHITENING_BYTES = bytes([0x93, 0xD7, 0x51, 0x21, 0x9C, 0x2F, 0x6C, 0xD0, 0xEF, 0x0F,
                         0xF8, 0x3D, 0xF1, 0x73, 0x20, 0x94, 0xED, 0x1E, 0x7C, 0xD8])


def bytes_to_bits(b):
    return np.unpackbits(np.frombuffer(bytes(b), np.uint8)).astype(np.int8)


def bits_to_bytes(bits):
    return np.packbits(np.asarray(bits, np.uint8)).tobytes()


SYNC = bytes_to_bits(SYNC_BYTES)
WHITENING = bytes_to_bits(WHITENING_BYTES)

# Dibit interleavers: dibit i of the coded stream goes to bit positions n, n+1 of the field.
def _dibit_interleaver(cols, rows=20):
    i = np.arange(cols * rows)
    return (i % cols) * 40 + (i // cols) * 2


IL_FICH = _dibit_interleaver(5)       # 100 dibits -> 200 bits
IL_CSD = _dibit_interleaver(9)        # 180 dibits -> 360 bits
IL_VCH = (np.arange(104) % 26) * 4 + np.arange(104) // 26   # DN voice: bit interleaver


# ---------------------------------------------------------------- CRC-16 (CCITT, inverted)
def crc16(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc ^ 0xFFFF


def add_crc(data):
    c = crc16(data)
    return bytes(data) + bytes([c >> 8, c & 0xFF])


def check_crc(data):
    return crc16(data[:-2]) == (data[-2] << 8 | data[-1])


# ---------------------------------------------------------------- Golay(24,12)
_GOLAY_POLY = 0xC75   # x^11 + x^10 + x^6 + x^5 + x^4 + x^2 + 1


def _golay23(d):
    r = d << 11
    for i in range(22, 10, -1):
        if r & (1 << i):
            r ^= _GOLAY_POLY << (i - 11)
    return (d << 11) | r


def golay24_encode(d):
    """12 data bits -> 24-bit codeword: data | 11 parity | overall even parity."""
    c = _golay23(d)
    return (c << 1) | (bin(c).count("1") & 1)


def _syndrome23(c):
    r = c
    for i in range(22, 10, -1):
        if r & (1 << i):
            r ^= _GOLAY_POLY << (i - 11)
    return r


# The (23,12) Golay code is perfect: every syndrome maps to one pattern of weight <= 3.
_SYN_TABLE = {}
for _w in range(4):
    from itertools import combinations
    for _pos in combinations(range(23), _w):
        _e = sum(1 << p for p in _pos)
        _SYN_TABLE.setdefault(_syndrome23(_e), _e)


def golay24_decode(c):
    """Returns (data, ok). ok is False when the overall parity shows 4 errors."""
    c23 = c >> 1
    e = _SYN_TABLE[_syndrome23(c23)]
    fixed = c23 ^ e
    nerr = bin(e).count("1")
    parity_ok = ((bin(fixed).count("1") + (c & 1)) & 1) == 0
    ok = nerr < 3 or parity_ok
    return fixed >> 11, ok


# ---------------------------------------------------------------- K=5 rate-1/2 conv code
# g1 = 1 + D^3 + D^4, g2 = 1 + D + D^2 + D^4 (D = one-bit delay)
_G5 = ((1, 0, 0, 1, 1), (1, 1, 1, 0, 1))


def conv5_encode(bits):
    reg = [0, 0, 0, 0]
    out = np.zeros(2 * len(bits), np.int8)
    for i, b in enumerate(bits):
        w = [int(b)] + reg
        out[2 * i] = sum(t * x for t, x in zip(_G5[0], w)) & 1
        out[2 * i + 1] = sum(t * x for t, x in zip(_G5[1], w)) & 1
        reg = [int(b)] + reg[:3]
    return out


def _conv5_trellis():
    # state = (d1 d2 d3 d4) as d1*8 + d2*4 + d3*2 + d4; next state on input b: b*8 + state>>1
    prev = np.zeros((16, 2), int)
    outs = np.zeros((16, 2, 2), int)
    for s in range(16):
        b = s >> 3
        for k, p in enumerate((((s & 7) << 1), ((s & 7) << 1) | 1)):
            prev[s, k] = p
            d = [(p >> 3) & 1, (p >> 2) & 1, (p >> 1) & 1, p & 1]
            w = [b] + d
            outs[s, k] = [sum(t * x for t, x in zip(g, w)) & 1 for g in _G5]
    return prev, 1 - 2 * outs


_P5, _S5 = _conv5_trellis()


def conv5_decode(llr, n_bits, terminated=True):
    """Soft Viterbi. llr: 2*n_bits values, positive means bit 0. Returns n_bits bits."""
    llr = np.asarray(llr, float).reshape(n_bits, 2)
    pm = np.full(16, -1e9)
    pm[0] = 0.0
    dec = np.zeros((n_bits, 16), np.int8)
    for i in range(n_bits):
        cand = pm[_P5] + _S5[:, :, 0] * llr[i, 0] + _S5[:, :, 1] * llr[i, 1]
        k = np.argmax(cand, 1)
        dec[i] = k
        pm = cand[np.arange(16), k]
        pm -= pm.max()
    s = 0 if terminated else int(np.argmax(pm))
    out = np.zeros(n_bits, np.int8)
    for i in range(n_bits - 1, -1, -1):
        out[i] = s >> 3
        s = _P5[s, dec[i, s]]
    return out


# ---------------------------------------------------------------- FICH
class FICH:
    def __init__(self, fi=FI_COMMS, cs=0, cm=0, bn=0, bt=0, fn=0, ft=6, dev=False,
                 mr=0, voip=False, dt=DT_VOICE_FR, sql=False, dgid=0, sotto=False):
        self.fi, self.cs, self.cm, self.bn, self.bt = fi, cs, cm, bn, bt
        self.fn, self.ft, self.dev, self.mr, self.voip, self.dt = fn, ft, dev, mr, voip, dt
        self.sql, self.dgid, self.sotto = sql, dgid, sotto

    def to_bytes(self):
        b0 = (self.fi << 6) | (self.cs << 4) | (self.cm << 2) | self.bn
        b1 = (self.bt << 6) | (self.fn << 3) | self.ft
        # bit 7 of byte 2 is unused by Fusion radios; sotto uses it (provisionally) as its flag
        b2 = (self.sotto << 7) | (self.dev << 6) | (self.mr << 3) | (self.voip << 2) | self.dt
        b3 = (self.sql << 7) | self.dgid
        return bytes([b0, b1, b2, b3])

    @classmethod
    def from_bytes(cls, b):
        return cls(fi=b[0] >> 6, cs=(b[0] >> 4) & 3, cm=(b[0] >> 2) & 3, bn=b[0] & 3,
                   bt=b[1] >> 6, fn=(b[1] >> 3) & 7, ft=b[1] & 7, dev=bool(b[2] & 0x40),
                   mr=(b[2] >> 3) & 7, voip=bool(b[2] & 4), dt=b[2] & 3,
                   sql=bool(b[3] & 0x80), dgid=b[3] & 0x7F, sotto=bool(b[2] & 0x80))

    def __eq__(self, o):
        return isinstance(o, FICH) and self.to_bytes() == o.to_bytes()

    def __repr__(self):
        return (f"FICH(fi={self.fi}, fn={self.fn}/{self.ft}, dt={self.dt}, dgid={self.dgid}, "
                f"sotto={self.sotto})")

    def encode(self):
        """-> 200 interleaved bits."""
        raw = add_crc(self.to_bytes())                          # 48 bits
        word = int.from_bytes(raw, "big")
        cw = [golay24_encode((word >> (36 - 12 * k)) & 0xFFF) for k in range(4)]
        bits = np.concatenate([bytes_to_bits(c.to_bytes(3, "big")) for c in cw] + [np.zeros(4, np.int8)])
        coded = conv5_encode(bits)                               # 200 bits
        out = np.zeros(FICH_BITS, np.int8)
        out[IL_FICH] = coded[0::2]
        out[IL_FICH + 1] = coded[1::2]
        return out

    @classmethod
    def decode(cls, llr):
        """llr: 200 soft values for the FICH field. Returns FICH or None."""
        llr = np.asarray(llr, float)
        coded = np.empty(FICH_BITS)
        coded[0::2] = llr[IL_FICH]
        coded[1::2] = llr[IL_FICH + 1]
        bits = conv5_decode(coded, 100)[:96]
        word = 0
        for k in range(4):
            c = int.from_bytes(bits_to_bytes(bits[24 * k:24 * k + 24]), "big")
            d, ok = golay24_decode(c)
            if not ok:
                return None
            word = (word << 12) | d
        raw = word.to_bytes(6, "big")
        if not check_crc(raw):
            return None
        return cls.from_bytes(raw[:4])


# ---------------------------------------------------------------- CSD (header/terminator)
def csd_encode(field20):
    """20 bytes -> 360 interleaved bits (Data FR coding)."""
    assert len(field20) == 20
    w = bytes(a ^ b for a, b in zip(field20, WHITENING_BYTES))
    bits = np.concatenate([bytes_to_bits(add_crc(w)), np.zeros(4, np.int8)])   # 180 bits
    coded = conv5_encode(bits)
    out = np.zeros(360, np.int8)
    out[IL_CSD] = coded[0::2]
    out[IL_CSD + 1] = coded[1::2]
    return out


def csd_decode(llr):
    llr = np.asarray(llr, float)
    coded = np.empty(360)
    coded[0::2] = llr[IL_CSD]
    coded[1::2] = llr[IL_CSD + 1]
    raw = bits_to_bytes(conv5_decode(coded, 180)[:176])
    if not check_crc(raw):
        return None
    return bytes(a ^ b for a, b in zip(raw[:20], WHITENING_BYTES))


def _csd_positions(which):
    """Payload bit positions of CSD1 (which=0) or CSD2 (which=1): 72 bits per section."""
    return np.concatenate([k * 144 + which * 72 + np.arange(72) for k in range(5)])


CSD_POS = (_csd_positions(0), _csd_positions(1))


def callsign_field(s):
    return s.upper().encode("ascii")[:10].ljust(10, b" ")


def header_payload(dest="CQCQCQ", src="N0CALL", csd2=b" " * 20):
    p = np.zeros(PAYLOAD_BITS, np.int8)
    p[CSD_POS[0]] = csd_encode(callsign_field(dest) + callsign_field(src))
    p[CSD_POS[1]] = csd_encode(bytes(csd2))
    return p


def decode_header_payload(llr):
    c1 = csd_decode(np.asarray(llr)[CSD_POS[0]])
    c2 = csd_decode(np.asarray(llr)[CSD_POS[1]])
    if c1 is None:
        return None
    return {"dest": c1[:10].decode("ascii", "replace").strip(),
            "src": c1[10:].decode("ascii", "replace").strip(), "csd2": c2}


# ---------------------------------------------------------------- frame assembly
def build_frame(fich, payload_bits):
    assert len(payload_bits) == PAYLOAD_BITS
    return np.concatenate([SYNC, fich.encode(), np.asarray(payload_bits, np.int8)])


def split_frame(llr960):
    llr960 = np.asarray(llr960)
    return llr960[SYNC_BITS:PAYLOAD_OFFSET], llr960[PAYLOAD_OFFSET:]
