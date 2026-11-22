"""sotto-tts prosody: phone sequences with their context, and the trained duration and
pitch trees (tools/tts_prosody.py trains them on Kokoro reading sentences). The synthesiser
uses its rules by default (tts/synth.py); the trees with --trained / model="auto".

    seq = phone_sequence(frontend.text_to_phrases(text))
    m = Model(open("tts/data/prosody.bin", "rb").read())
    m.time(seq)             # sets each phone's t0, t1 (s)
    f0 = m.f0_track(seq, n_frames, 0.02)

Both models are regression trees, walked with integer compares: each internal node holds a
feature number and a threshold, each leaf the prediction (a log duration, or three log
pitch ratios for a vowel: 20%, 50% and 80% of the way through it, against the voice's
median pitch). The format is small and simple enough for the K6:

    'STP1', median pitch (Hz, u16), pause after '.' ',' '?' '!' (u8 each, 5 ms units),
    duration tree, pitch tree. A tree: node count (u16), then per node in pre-order either
    0xFF + leaf values (s16 each, 1/256 units) or feature (u8) + threshold (s16, 1/16
    units) + offset to the right child (u16); the left child follows its parent.

SPDX-License-Identifier: MIT
"""
import struct
import numpy as np
from .phones import (PHONES, ID, VOWELS, STOPS, AFFRICATES, FRICATIVES, NASALS, LIQUIDS,
                     DIPHTHONGS, VOICED_C, is_vowel)

AUX = set("is are was were do does did can could will would shall should have has had am "
          "may might must".split())
ENDS = {".": 0, ",": 1, "?": 2, "!": 3}


def pclass(p):
    if p == "PAU":
        return 0
    if is_vowel(p):
        return 1
    if p in STOPS:
        return 2
    if p in FRICATIVES:
        return 3
    if p in NASALS:
        return 4
    if p in LIQUIDS:
        return 5
    return 6                                    # affricates


def phone_sequence(phrases, spell_gap=True):
    """Phrases (tts.frontend) -> phone dicts with p, stress, content, word (index in its
    phrase), phrase, spell and, for pauses, the punctuation that made them ('end')."""
    seq = [dict(p="PAU", stress=0, content=False, word=-1, phrase=-1, spell=False, end="^")]
    for j, ph in enumerate(phrases):
        words = ph["words"]
        flat = [(wi, p, s) for wi, w in enumerate(words) for p, s in w["phones"]]
        for k, (wi, p, s) in enumerate(flat):
            w = words[wi]
            seq.append(dict(p=p, stress=s, content=w["content"], word=wi, phrase=j,
                            spell=bool(w.get("spell")), wtext=w["text"]))
            last_of_word = k + 1 == len(flat) or flat[k + 1][0] != wi
            if spell_gap and last_of_word and w.get("spell") and k + 1 < len(flat):
                seq.append(dict(p="PAU", stress=0, content=False, word=-1, phrase=j,
                                spell=True, end="spell"))
        end = ph["end"] if j < len(phrases) - 1 else "$"
        seq.append(dict(p="PAU", stress=0, content=False, word=-1, phrase=-1, spell=False,
                        end=end, pend=ph["end"]))
    # phrase-level facts every phone of the phrase needs
    for j, ph in enumerate(phrases):
        P = [q for q in seq if q["phrase"] == j and q["p"] != "PAU"]
        vow = [q for q in P if is_vowel(q["p"])]
        acc = [q for q in vow if q["stress"] == 1 and q["content"]]
        words = ph["words"]
        yesno = ph["end"] == "?" and bool(words) and words[0]["text"] in AUX
        for i, q in enumerate(vow):
            q["syl_from"], q["syl_to"] = i, len(vow) - 1 - i
        for i, q in enumerate(acc):
            q["acc_from"], q["acc_to"] = i, len(acc) - 1 - i
        nv = 0
        for q in P:
            q["nsyl"] = len(vow)
            q["nwords"] = len(words)
            q["ptype"] = ENDS.get(ph["end"], 0)
            q["yesno"] = yesno
            q["pidx"], q["nphr"] = j, len(phrases)
            q["acc_before"] = sum(1 for a in acc if a is not q and vow.index(a) < nv) if acc else 0
            if is_vowel(q["p"]):
                nv += 1
            q["syl_left"] = len(vow) - nv          # vowels after this phone in the phrase
    return seq


def features(seq):
    """Per phone: {'dur': duration features, 'pitch': pitch features for a vowel or None}."""
    out = []
    # per word: phone positions and syllables
    for i, q in enumerate(seq):
        if q["p"] == "PAU":
            out.append(dict(dur=None, pitch=None))
            continue
        same = [r for r in seq if r["phrase"] == q["phrase"] and r["word"] == q["word"] and r["p"] != "PAU"]
        pos = next(k for k, r in enumerate(same) if r is q)
        wv = [k for k, r in enumerate(same) if is_vowel(r["p"])]
        sylw = sum(1 for k in wv if k < pos)
        onset = 0 if (wv and pos < wv[0]) else 2 if (wv and pos > wv[-1]) else 1
        prev, nxt = seq[i - 1]["p"] if i else "PAU", seq[i + 1]["p"] if i + 1 < len(seq) else "PAU"
        p = q["p"]
        reduced = p in ("AX", "AXR") or (p in ("IH", "UH", "IY") and q["stress"] == 0)
        final = q["syl_left"] == 0 or (is_vowel(p) and q.get("syl_to", 9) == 0)
        d = [ID[p], int(is_vowel(p)), int(p in STOPS), int(p in FRICATIVES), int(p in NASALS),
             int(p in LIQUIDS), int(p in AFFRICATES), int(p in VOICED_C), int(p in DIPHTHONGS),
             int(reduced), q["stress"], int(q["content"]), pos, len(same) - 1 - pos, len(same),
             len(wv), int(final), q["syl_left"], q["nsyl"] - q["syl_left"], q["ptype"],
             pclass(prev), pclass(nxt), int(prev == "PAU"), int(nxt == "PAU"),
             int(nxt in VOICED_C or is_vowel(nxt)), int(q["spell"]), onset, q["nwords"]]
        pf = None
        if is_vowel(p):
            pf = [q["stress"], int(q["content"]), q["syl_from"], q["syl_to"],
                  round(16 * q["syl_from"] / max(1, q["nsyl"] - 1)), q["ptype"], q["word"],
                  q["nwords"], q.get("acc_from", -1), q.get("acc_to", -1), q["acc_before"],
                  len(wv), sylw, int(q["spell"]), q["pidx"], q["nphr"],
                  int(q["pidx"] == q["nphr"] - 1), int(q["yesno"]), int(reduced),
                  int(q["stress"] == 1 and q["content"])]
        out.append(dict(dur=d, pitch=pf))
    return out


# ------------------------------------------------------------------ tree format
def _pack_tree(m, scale_out=256):
    t = m.tree_
    out = bytearray()
    count = [0]

    def emit(n):
        count[0] += 1
        if t.children_left[n] == -1:
            v = np.atleast_1d(t.value[n].ravel())
            out.extend(b"\xff" + b"".join(struct.pack("<h", int(np.clip(round(x * scale_out), -32768, 32767))) for x in v))
            return
        start = len(out)
        thr = int(np.floor(t.threshold[n] * 16))          # x <= thr/16 (features are k/16 grid)
        out.extend(struct.pack("<BhH", t.feature[n], thr, 0))
        emit(t.children_left[n])
        off = len(out) - start
        struct.pack_into("<H", out, start + 3, off)
        emit(t.children_right[n])
    emit(0)
    return struct.pack("<H", count[0]) + bytes(out)


def write_model(dur, pitch, med, pause):
    pz = [min(255, int(round(pause.get(k, 0.3) / 0.005))) for k in (".", ",", "?", "!")]
    return b"STP1" + struct.pack("<H4B", int(round(med)), *pz) + _pack_tree(dur) + _pack_tree(pitch)


class Tree:
    def __init__(self, buf, pos, nout):
        self.buf, self.nout = buf, nout
        (self.count,) = struct.unpack_from("<H", buf, pos)
        self.start = pos + 2
        # walk once to find the end
        p, n = self.start, 0
        while n < self.count:
            if buf[p] == 0xFF:
                p += 1 + 2 * nout
            else:
                p += 5
            n += 1
        self.end = p

    def predict(self, x):
        b, p = self.buf, self.start
        while b[p] != 0xFF:
            f, thr, off = struct.unpack_from("<BhH", b, p)
            p = p + 5 if x[f] * 16 <= thr else p + off
        return [struct.unpack_from("<h", b, p + 1 + 2 * k)[0] / 256 for k in range(self.nout)]


class Model:
    def __init__(self, raw):
        assert raw[:4] == b"STP1"
        med, *pz = struct.unpack_from("<H4B", raw, 4)
        self.f0 = med
        self.pause = dict(zip((".", ",", "?", "!"), [v * 0.005 for v in pz]))
        self.dur = Tree(raw, 10, 1)
        self.pitch = Tree(raw, self.dur.end, 3)
        self.size = len(raw)

    def time(self, seq, rate=1.0, feats=None):
        """Sets t0, t1 on every phone: the duration tree's prediction, pauses from the table
        (a callsign's gaps 80 ms, the start 150 ms, the end 200 ms)."""
        feats = feats or features(seq)
        t = 0.0
        for q, f in zip(seq, feats):
            if q["p"] == "PAU":
                e = q["end"]
                d = {"^": 0.15, "$": 0.2, "spell": 0.08}.get(e, self.pause.get(e, 0.3))
            else:
                d = float(np.exp(self.dur.predict(f["dur"])[0]))
            d = max(d / rate, 0.02)
            q["dur"], q["t0"], q["t1"] = d, t, t + d
            t += d
        return seq

    YESNO_RISE = 0.4          # log pitch added at the end of a yes/no question (x 1.5)

    def f0_track(self, seq, n, frame, pitch=1.0, feats=None):
        """Per frame pitch (Hz): three targets per vowel, straight lines (in log) between.
        A yes/no question (a phrase ending '?' that starts with an auxiliary) also rises from
        its last accent to its end: the corpus has too few of them (and Kokoro reads them
        nearly level) for the tree to learn it."""
        feats = feats or features(seq)
        tt, lf, ph = [], [], []
        for q, f in zip(seq, feats):
            if f["pitch"] is None:
                continue
            v = self.pitch.predict(f["pitch"])
            for x, l in zip((0.2, 0.5, 0.8), v):
                tt.append(q["t0"] + x * (q["t1"] - q["t0"]))
                lf.append(l)
                ph.append(q)
        for j in {q["phrase"] for q in ph if q["yesno"]}:
            idx = [k for k, q in enumerate(ph) if q["phrase"] == j]
            acc = [k for k in idx if ph[k]["stress"] == 1 and ph[k]["content"]]
            k0 = acc[-1] - 1 if acc else idx[0]          # the last accent's middle target
            ta, te = tt[k0], tt[idx[-1]]
            for k in idx:
                if tt[k] > ta and te > ta:
                    lf[k] += self.YESNO_RISE * (tt[k] - ta) / (te - ta)
        base = np.log(self.f0 * pitch)
        if not tt:
            return np.full(n, np.exp(base))
        tc = np.arange(n) * frame
        return np.exp(base + np.interp(tc, tt, lf))
