"""sotto v3.8: unvoiced consonants (docs/unvoiced-hiss.md).

Same 48-bit frame as v3.7, 16 kHz in and out:
  - unvoiced halves are synthesised as noise harmonics 50 Hz apart (not at the coded pitch),
    so the 7 pitch bits of an all-unvoiced (UU) frame carry nothing. They now carry a 7-bit
    index for the 4-8 kHz band: four band levels (4-5, 5-6, 6-7, 7-8 kHz) as a correction
    to a guess the decoder makes from the 0-4 kHz envelope;
  - unvoiced frames whose envelope tilts upward (real fricatives) get +3 dB, which undoes
    the level the noise synthesis loses (listening round 11);
  - encoder: a frame where 4-8 kHz jumps by 12 dB (a t/p/k burst) is sent as UU so it
    gets an index; a loud, low-heavy frame the tracker called UU (a creaky vowel onset,
    "act" in round 12) is sent as MM with its neighbour's pitch;
  - decoder: 4-8 kHz noise in UU frames (and in the unvoiced half of a neighbouring edge
    frame) at the coded level, and in mixed frames at the guess - 3 dB. Lost frames use
    the concealed bits and the concealment fade.
The 0-4 kHz part is v3.7 upsampled; a v3.7 decoder reads a v3.8 stream with rougher noise
in UU frames and no high band.
"""
import os
import numpy as np
from scipy.signal import resample_poly

import vocoder_lab as vl

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "data", "hiss_band.npz")

N, H = 320, 160                              # 20 ms window, 10 ms hop at 16 kHz
WIN = np.sqrt(np.hanning(N + 1)[:N])         # sqrt-Hann: squares sum to 1 at 50% overlap
FR = np.fft.rfftfreq(N, 1 / 16000)
HB = [(4000, 5000), (5000, 6000), (6000, 7000), (7000, 8000)]
HBC = np.array([4500.0, 5500, 6500, 7500])
FB = np.array([1250.0, 1750, 2250, 2750, 3250, 3600, 3800])   # guess inputs (Hz)
HB_LAG = 2                                   # STFT frame t of the output = model frame t + 2
W50 = 2 * np.pi / 160
UV_GAIN = 3.0
BURST_DB = 12.0
MIXED_DB = -3.0
KLO, KHI = vl.KFREQ < 1000, vl.KFREQ > 2000


def stft(x):
    n = max(0, (len(x) - N) // H + 1)
    return np.fft.rfft(np.stack([x[i * H:i * H + N] * WIN for i in range(n)]), axis=1)


def istft(X, n):
    y = np.zeros(n + N)
    for i, f in enumerate(np.fft.irfft(X, N, axis=1) * WIN):
        y[i * H:i * H + N] += f
    return y[:n]


def bands_db(P, bands):
    return np.stack([10 * np.log10(P[:, (FR >= a) & (FR < b)].mean(1) + 1e-12) for a, b in bands], 1)


def model_env(m):
    """dB envelope of each decoded model frame at FB."""
    out = np.zeros((len(m), len(FB)))
    for k, r in enumerate(m):
        L = r["L"]
        f = np.arange(1, L + 1) * r["Wo"] * 4000 / np.pi
        out[k] = np.interp(FB, f, 20 * np.log10(r["A"][1:L + 1] + 1e-9))
    return out


def frame_map(m, bits, nfr):
    """Per output STFT frame: envelope features, voicing class (0 U, 1 V, 2 M), codec frame,
    and whether that codec frame is UU."""
    k = np.clip(np.arange(nfr) + HB_LAG, 0, len(m) - 1)
    E = model_env(m)[k]
    v = np.minimum(m["voiced"], 2)[k]
    code = bits[:, 0] * 2 + bits[:, 1]
    f = np.clip(np.arange(nfr) + HB_LAG, 0, 2 * len(code) - 1) // 2
    return E, v, f, code[f] == 0


def guess(W, E, v):
    """Per-class linear guess of the four high-band levels (dB) from the 0-4 kHz envelope."""
    ref = E[:, 6]
    F = np.column_stack([np.ones(len(E)), E[:, :6] - ref[:, None], ref])
    out = np.zeros((len(E), 4))
    for c in range(3):
        s = v == c
        out[s] = F[s] @ W[c] + ref[s, None]
    return out


def uu_residuals(hb, p, f, uu):
    """Mean (true - guess) over the STFT frames of each UU codec frame -> {frame: 4 dB}."""
    out = {}
    for g in np.unique(f[uu]):
        s = (f == g) & uu
        out[int(g)] = (hb[s] - p[s]).mean(0)
    return out


def index_of(bits_row, nb=7):
    return int("".join(map(str, bits_row[2:2 + nb])), 2)


# ---------------------------------------------------------------- vowel side channel
WIN_FRAMES = 100              # one message per 2 s of frames (frame numbers known to both ends)
MSG_BITS = 16                 # 12 payload + CRC-4, one bit in each of the window's first 16 UU frames
BPOS = np.arange(4) - 1.5


def crc4(bits):
    r = 0
    for b in bits:                                  # x^4 + x + 1
        fb = ((r >> 3) & 1) ^ b
        r = ((r << 1) & 0xF) ^ (0x3 if fb else 0)
    return [(r >> (3 - i)) & 1 for i in range(4)]


def q_offset(r):
    """4 band offsets (dB) -> (level code 0..15: -10..20 dB in 2 dB; tilt code 0..3:
    -3/-1/1/3 dB per band)."""
    li = int(np.clip(np.round((r.mean() + 10) / 2), 0, 15))
    ti = int(np.clip(np.round((np.polyfit(BPOS, r, 1)[0] + 3) / 2), 0, 3))
    return li, ti


def offset_of(li, ti):
    return (-10 + 2 * li) + (-3 + 2 * ti) * BPOS


def pack_msg(codes):
    """[(liV, tiV), (liM, tiM)] -> 16 bits"""
    b = []
    for li, ti in codes:
        b += [(li >> (3 - i)) & 1 for i in range(4)] + [(ti >> (1 - i)) & 1 for i in range(2)]
    return b + crc4(b)


def unpack_msg(b):
    if len(b) < MSG_BITS or crc4(b[:12]) != list(b[12:16]):
        return None
    v = lambda x: int("".join(map(str, x)), 2)
    return [(v(b[0:4]), v(b[4:6])), (v(b[6:10]), v(b[10:12]))]


class SottoV38(vl.SottoV37):
    """See the module docstring. encode() and decode_audio16() work at 16 kHz; decode()
    returns the 8 kHz model like the other versions."""

    def __init__(self, model=MODEL, vowel=None, **kw):
        """vowel: None (no high band in voiced frames), "guess" (voiced frames at the guess
        - 3 dB) or "adaptive" (voiced and mixed frames at the guess + a per-speaker offset
        sent one bit per UU frame; the UU index is then 6 bits)."""
        super().__init__(**kw)
        self.vowel = vowel
        if model:                                       # None while training the guess
            z = np.load(model, allow_pickle=True)
            self.W, self.cb = z["W"].item(), z["cb"]
            if vowel == "adaptive":
                self.cb = z["cb6"]
        self.nb = 6 if vowel == "adaptive" else 7

    # ---------------------------------------------------------------- decoder hooks
    def _model_hook(self, m, rk, en):
        u = np.where(m["voiced"] == 0)[0]
        if len(u):
            mu = vl.set_wo(m[u], np.full(len(u), W50), np.zeros(len(u), int))
            m[u] = vl.set_energy(vl.from_rate_k(mu, rk[u]), en[u])
            for k in u:
                if rk[k, KLO].mean() - rk[k, KHI].mean() < 0:
                    m[k]["A"] *= 10 ** (UV_GAIN / 20)
        return m

    # ---------------------------------------------------------------- encoder
    def encode(self, x16):
        bits, hb, m = self.encode_low(x16)
        E, v, f, uu = frame_map(m, bits, len(hb))
        p = guess(self.W, E, v)
        res = uu_residuals(hb, p, f, uu)
        code = bits[:, 0] * 2 + bits[:, 1]
        nb = self.nb
        for g in np.where(code == 0)[0]:
            i = int(np.argmin(((self.cb - res[g]) ** 2).sum(1))) if g in res else 0
            bits[g, 2:2 + nb] = [(i >> (nb - 1 - b)) & 1 for b in range(nb)]
        if self.vowel == "adaptive":
            self._side_channel(bits, hb, p, E, v, f)
        return bits

    def _side_channel(self, bits, hb, p, E, v, f):
        """Window w carries the running mean of (true - guess) over the voiced and mixed
        frames of windows 0..w-1, so the encoder needs no look-ahead."""
        code = bits[:, 0] * 2 + bits[:, 1]
        live = E[:, 6] > np.maximum.accumulate(E[:, 6]) - 35
        acc = {1: [], 2: []}
        for w in range((len(bits) + WIN_FRAMES - 1) // WIN_FRAMES):
            uuf = [g for g in range(w * WIN_FRAMES, min(len(bits), (w + 1) * WIN_FRAMES)) if code[g] == 0]
            codes = [q_offset(np.mean(acc[c], 0)) if acc[c] else (5, 1) for c in (1, 2)]  # (5,1): 0 dB, -1/band
            for g, b in zip(uuf, pack_msg(codes)):
                bits[g, 8] = b
            ts = np.where((f >= w * WIN_FRAMES) & (f < (w + 1) * WIN_FRAMES))[0]
            for t in ts:
                if v[t] in (1, 2) and live[t]:
                    acc[v[t]].append(hb[t] - p[t])
    def encode_low(self, x16):
        """-> (bits without the high-band index, true band levels per STFT frame, the
        encoder's own decoded model)."""
        x8 = resample_poly(x16, 1, 2)
        bits = vl.SottoV37.encode(self, x8)
        self._onsets(x8, bits)
        P = np.abs(stft(x16)) ** 2
        hb = bands_db(P, HB)
        m = self.decode(bits)
        _, _, f, _ = frame_map(m, bits, len(P))
        top, low = bands_db(P, [(4000, 8000)])[:, 0], bands_db(P, [(0, 3900)])[:, 0]
        for t in np.where((top[1:] - top[:-1] > BURST_DB) & (top[1:] > low[1:] - 15))[0] + 1:
            bits[f[t], 0] = bits[f[t], 1] = 0            # burst: send as UU
        return bits, hb, self.decode(bits)

    def _onsets(self, x8, bits, loud_db=10.0, lowdom=3.0):
        m = vl.analyse(x8, self.PITCH)
        if len(m) % 2:
            m = np.concatenate([m, m[-1:]])
        rk = vl.to_rate_k(m)
        en = rk.mean(1)
        loud = en > np.percentile(en, 90) - loud_db
        code = bits[:, 0] * 2 + bits[:, 1]
        for g in range(len(bits)):
            k = 2 * g
            if code[g] or not loud[k] or rk[k, KLO].mean() - rk[k, KHI].mean() <= lowdom:
                continue
            near = [h for d in (1, -1, 2, -2, 3, -3) for h in [g + d]
                    if 0 <= h < len(bits) and code[h] in (1, 2)]
            if near:
                bits[g, 0], bits[g, 1] = 1, 0           # MM, with the neighbour's pitch
                bits[g, 2:9] = bits[near[0], 2:9]

    def _read_side(self, bits, good):
        """-> per window {1: V offset, 2: M offset}; a message (window w) applies from
        window w + 1. Any lost frame in a window drops its message."""
        nw = (len(bits) + WIN_FRAMES - 1) // WIN_FRAMES
        cur = {1: offset_of(5, 1), 2: offset_of(5, 1)}
        out = []
        for w in range(nw + 1):
            out.append(dict(cur))
            g0, g1 = w * WIN_FRAMES, min(len(bits), (w + 1) * WIN_FRAMES)
            if g0 >= len(bits) or not np.all(good[g0:g1]):
                continue
            seg = bits[g0:g1]
            msg = unpack_msg([int(r[8]) for r in seg if r[0] == 0 and r[1] == 0][:MSG_BITS])
            if msg:
                cur = {1: offset_of(*msg[0]), 2: offset_of(*msg[1])}
        return out

    # ---------------------------------------------------------------- 16 kHz decoder
    def decode_audio16(self, bits, good=None, n16=None, seed=0):
        bits = np.asarray(bits)
        good = np.ones(len(bits), bool) if good is None else np.asarray(good, bool)
        b2, last, run, r = bits.copy(), None, np.zeros(len(bits), int), 0
        for g in range(len(bits)):                      # the bits concealment decodes
            r = 0 if good[g] else r + 1
            run[g] = r
            if good[g]:
                last = bits[g].copy()
            elif last is not None:
                b2[g] = last
        m = self.decode(bits, good)
        y8 = vl.synthesise(m)[vl.ar.CODEC_DELAY:]
        n8 = n16 // 2 if n16 else len(y8)
        y16 = resample_poly(np.pad(y8, (0, max(0, n8 - len(y8))))[:n8], 2, 1)
        nfr = max(0, (len(y16) - N) // H + 1)
        E, v, f, uu = frame_map(m, b2, nfr)
        p = guess(self.W, E, v)
        code = b2[:, 0] * 2 + b2[:, 1]
        off = self._read_side(bits, good) if self.vowel == "adaptive" else None
        mask = np.zeros(nfr)
        for t in range(nfr):
            src = f[t] if uu[t] else None
            if src is None and v[t] == 0:               # unvoiced half of an edge frame
                src = next((g for g in (f[t] - 1, f[t] + 1) if 0 <= g < len(code) and code[g] == 0), None)
            if src is not None:
                p[t] += self.cb[index_of(b2[src], self.nb)]
                mask[t] = 1
            elif self.vowel == "adaptive" and v[t] in (1, 2):
                p[t] += off[f[t] // WIN_FRAMES][v[t]]
                mask[t] = 1
            elif v[t] == 2 or (self.vowel == "guess" and v[t] == 1):
                p[t] += MIXED_DB
                mask[t] = 1
        fade = np.array([0.0 if run[g] == 0 else -80.0 if run[g] > 4 else -6.0 * max(0, run[g] - 2)
                         for g in f])
        p += fade[:, None] + UV_GAIN
        lvl = np.stack([np.interp(FR, HBC, h) for h in p]) if nfr else np.zeros((0, len(FR)))
        mag = np.sqrt(10 ** (lvl / 10)) * np.clip((FR - 3900) / 200, 0, 1) * mask[:, None]
        ph = np.exp(2j * np.pi * np.random.default_rng(seed).random(mag.shape))
        return y16 + istft(mag * ph, len(y16))
