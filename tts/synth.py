"""sotto-tts: text in, sotto 1200 superframes out.

    python -m tts.synth "This is AG7EW." --table tts/data/diphone.stt --wav out.wav [--sot out.sot]

The synthesiser never makes audio itself: it writes a sotto parameter track (per 20 ms frame
a voicing code, a pitch, an energy and a spectral shape), packs it into sotto 1200 superframes
with the reference encoder's quantiser, and any sotto 1200 decoder (the K6's fixed-point one
here: the v3.7 fixed-point build, build/c37/fixed/sotto_dec_fx) turns it into speech.

Steps: text -> phrases of words -> phones with stress (tts.frontend) -> durations and an
intonation contour (the rules below, or the trained trees in tts/prosody.py) -> keyframes
from the unit table (tts.table): each phone's 2-3 targets (robotic table) or the diphones
that meet in each phone's middle (diphone table) -> frames every 20 ms, interpolated between keyframes -> superframes.
SPDX-License-Identifier: MIT
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
from . import frontend, table as T  # noqa: E402
from .phones import PHONES, is_vowel  # noqa: E402

FRAME = 0.02
SLOW = 1.15      # the corpus medians run 15% faster than Kokoro reads a plain sentence
SPELL_GAP = 0.2  # s between callsign elements (radio pacing; 0.08 before the whole-word units)
AUX = set("is are was were do does did can could will would shall should have has had am may might must".split())
# phone stand-ins for a pair the diphone table lacks
SUB = {"AXR": "ER", "ER": "AXR", "AX": "AH", "AH": "AX", "ZH": "SH", "NG": "N", "OY": "AO",
       "UH": "UW", "TH": "F", "DH": "V", "IH": "IY", "IY": "IH", "EH": "AE", "AE": "EH",
       "AA": "AO", "AO": "AA", "UW": "UH", "Y": "IY", "W": "UW", "HH": "PAU"}

_VQ = None


def vq():
    global _VQ
    if _VQ is None:
        import sotto_lr
        _VQ = sotto_lr.Sotto1200().vq
    return _VQ


def shape_of(fr):
    """Table frame -> DCT coefficients 1..19 (sum of its codebook stages)."""
    q = vq()
    return sum(q.cb[k][i] for k, i in enumerate(fr["si"]))


# ------------------------------------------------------------------ phones and timing
def phone_plan(text, tab, rate=1.0):
    """Text -> list of phone dicts (p, stress, content, word, phrase, t0, t1) and phrases."""
    phrases = frontend.text_to_phrases(text)
    seq = [dict(p="PAU", stress=0, content=False, word=-1, phrase=-1, dur=0.12)]
    for j, ph in enumerate(phrases):
        words = ph["words"]
        # the phrase's last vowel and what follows it are lengthened
        flat = [(wi, p, s) for wi, w in enumerate(words) for p, s in w["phones"]]
        last_v = max([k for k, (_, p, _) in enumerate(flat) if is_vowel(p)], default=len(flat))
        for k, (wi, p, s) in enumerate(flat):
            content = words[wi]["content"]
            d = tab["dur"][p][0 if s > 0 else 1]
            if not content:
                d *= 0.85
            if k >= last_v:
                d *= 1.35
            seq.append(dict(p=p, stress=s, content=content, word=wi, phrase=j, dur=SLOW * d / rate))
            last_of_word = k + 1 == len(flat) or flat[k + 1][0] != wi
            if last_of_word and words[wi].get("spell") and k + 1 < len(flat):
                seq.append(dict(p="PAU", stress=0, content=False, word=-1, phrase=j, dur=SPELL_GAP / rate))
        pause = 0.22 if ph["end"] == "," else 0.4
        if j == len(phrases) - 1:
            pause = 0.2
        seq.append(dict(p="PAU", stress=0, content=False, word=-1, phrase=-1, dur=pause))
    t = 0.0
    for q in seq:
        q["dur"] = max(q["dur"], 0.03)
        q["t0"], q["t1"] = t, t + q["dur"]
        t += q["dur"]
    return seq, phrases


def f0_track(seq, phrases, f0, n):
    """Intonation: a falling baseline per phrase, a peak on each content word's stressed
    vowel (each a little lower than the one before), and a phrase-final fall, continuation
    rise (comma) or question rise (a yes/no question: the phrase starts with an auxiliary)."""
    pts = []
    for j, ph in enumerate(phrases):
        P = [q for q in seq if q["phrase"] == j]
        if not P:
            continue
        t0, t1 = P[0]["t0"], P[-1]["t1"]
        span = max(t1 - t0, 0.2)
        base = lambda t: f0 * (1.02 - 0.15 * (t - t0) / span)
        pts.append((t0, base(t0)))
        acc = [q for q in P if q["stress"] == 1 and q["content"] and is_vowel(q["p"])]
        yesno = ph["end"] == "?" and ph["words"] and ph["words"][0]["text"] in AUX
        for k, q in enumerate(acc):
            pk = f0 * max(1.32 - 0.07 * k, 1.12)
            pts.append((q["t0"], base(q["t0"]) * 1.02))
            pts.append((0.5 * (q["t0"] + q["t1"]), pk * (1.0 - 0.15 * (q["t0"] - t0) / span)))
        if ph["end"] == "," :
            pts.append((t1, f0 * 1.1))
        elif yesno:
            pts.append((t1, f0 * 1.5))
        else:
            pts.append((t1, f0 * 0.76))
    pts.sort()
    if not pts:
        return np.full(n, f0)
    tt = np.array([p[0] for p in pts])
    lf = np.log([p[1] for p in pts])
    tc = np.arange(n) * FRAME
    return np.exp(np.interp(tc, tt, lf))


# ------------------------------------------------------------------ keyframes
def keyframes_robot(seq, tab, tau=0.015):
    """Each phone's targets held steady over equal parts of the phone, with quick (2 x tau)
    glides between them and into the next phone."""
    K = []
    for i, q in enumerate(seq):
        if q["p"] == "PAU":
            K.append(dict(t=q["t0"] + 0.01, c=None, ei=0, code=0))
            K.append(dict(t=q["t1"] - 0.01, c=None, ei=0, code=0))
            continue
        fr = tab["units"][q["p"]]
        n = len(fr)
        seg = q["dur"] / n
        e = min(tau, seg / 4)
        for j, f in enumerate(fr):
            a = q["t0"] + seg * j
            for t in (a + e, a + seg - e):
                K.append(dict(t=t, c=shape_of(f), ei=f["ei"], code=f["code"]))
    return K


def find_unit(tab, a, b):
    """The diphone a-b, or stand-ins: (split, frames, how)."""
    U = tab["units"]
    for x, y in ((a, b), (SUB.get(a, a), b), (a, SUB.get(b, b)), (SUB.get(a, a), SUB.get(b, b))):
        if (x, y) in U:
            return U[(x, y)] + ((x, y) != (a, b),)
    left = next((U[(a, z)] for z in ("AX", "AH", "PAU") + tuple(PHONES) if (a, z) in U), None)
    right = next((U[(z, b)] for z in ("AX", "AH", "PAU") + tuple(PHONES) if (z, b) in U), None)
    fr = (left[1][:left[0]] if left else []) + (right[1][right[0]:] if right else [])
    return (left[0] if left else 0), fr, True


def keyframes_diphone(seq, tab, smooth=0.5):
    """Keyframes from the diphones meeting in each phone's middle. With smooth > 0 the
    mismatch where two diphones meet (shape and energy) is spread over both halves of the
    phone: each side moves halfway towards the other, fading to nothing at the phone's
    edges, so joins don't click and formants glide."""
    parts, subs = [], 0              # per unit: (left keyframes, right keyframes)
    for i in range(len(seq) - 1):
        qa, qb = seq[i], seq[i + 1]
        split, fr, sub = find_unit(tab, qa["p"], qb["p"])
        subs += sub
        ma, mb = 0.5 * (qa["t0"] + qa["t1"]), 0.5 * (qb["t0"] + qb["t1"])
        pr = []
        for part, (t0, t1) in ((fr[:split], (ma, qa["t1"])), (fr[split:], (qb["t0"], mb))):
            m = len(part)
            pr.append([dict(t=t0 + (t1 - t0) * (j + 0.5) / m, c=shape_of(f) if f["ei"] > 0 else None,
                            ei=float(f["ei"]), code=f["code"], w=(j + 0.5) / m) for j, f in enumerate(part)])
        parts.append(pr)
    if smooth:
        for i in range(1, len(seq) - 1):
            if seq[i]["p"] == "PAU":
                continue
            R, L = parts[i - 1][1], parts[i][0]      # phone i's first half, second half
            if not R or not L:
                continue
            a, b = R[-1], L[0]
            if a["c"] is not None and b["c"] is not None:
                d = smooth * 0.5 * (b["c"] - a["c"])
                for k in R:
                    if k["c"] is not None:
                        k["c"] = k["c"] + d * k["w"]
                for k in L:
                    if k["c"] is not None:
                        k["c"] = k["c"] - d * (1 - k["w"])
            if a["ei"] > 0 and b["ei"] > 0:
                de = smooth * 0.5 * (b["ei"] - a["ei"])
                for k in R:
                    if k["ei"] > 0:
                        k["ei"] += de * k["w"]
                for k in L:
                    if k["ei"] > 0:
                        k["ei"] -= de * (1 - k["w"])
    K = [k for pr in parts for side in pr for k in side]
    return K, subs


def render(K, n):
    """Keyframes -> per-frame DCT shape, energy code and voicing code."""
    K = sorted(K, key=lambda k: k["t"])
    # silent keyframes borrow the nearest voiced shape so that fades keep their colour
    last = next((k["c"] for k in K if k["c"] is not None), np.zeros(19))
    for k in K:
        if k["c"] is None:
            k["c"] = last
        else:
            last = k["c"]
    tk = np.array([k["t"] for k in K])
    C = np.array([k["c"] for k in K])
    E = np.array([k["ei"] for k in K], float)
    V = np.array([k["code"] for k in K])
    tc = np.arange(n) * FRAME + 0.5 * FRAME
    c = np.stack([np.interp(tc, tk, C[:, d]) for d in range(C.shape[1])], 1)
    e = np.interp(tc, tk, E)
    near = np.abs(tc[:, None] - tk[None, :]).argmin(1)
    return c, np.round(e).astype(int), V[near]


# ------------------------------------------------------------------ top level
_PROSODY = {}


def load_prosody(path=None):
    """The trained duration and pitch trees (tts/prosody.py), or None if there are none."""
    path = path or os.path.join(HERE, "data", "prosody.bin")
    if path not in _PROSODY:
        from . import prosody
        _PROSODY[path] = prosody.Model(open(path, "rb").read()) if os.path.exists(path) else None
    return _PROSODY[path]


_WORDS = {}


def load_words(path=None):
    """The whole-word callsign units (tts/data/words.stw), or None."""
    path = path or os.path.join(HERE, "data", "words.stw")
    if path not in _WORDS:
        _WORDS[path] = T.read_words(open(path, "rb").read()) if os.path.exists(path) else None
    return _WORDS[path]


def _word_spans(seq, phrases):
    """{(phrase, word): [seq indices]} for the callsign elements (spell words)."""
    out = {}
    for i, q in enumerate(seq):
        if q["p"] == "PAU" or q["phrase"] < 0:
            continue
        w = phrases[q["phrase"]]["words"][q["word"]]
        if w.get("spell"):
            out.setdefault((q["phrase"], q["word"]), []).append(i)
    return out


def fit_words(seq, phrases, words):
    """Stretch each callsign element that has a whole-word unit to the unit's length; returns
    [(seq index of its first phone, frames)]."""
    spans = []
    for (j, wi), idx in _word_spans(seq, phrases).items():
        fr = words["words"].get(phrases[j]["words"][wi]["text"])
        if not fr:
            continue
        cur = sum(seq[i]["dur"] for i in idx)
        for i in idx:
            seq[i]["dur"] *= len(fr) * FRAME / cur
        spans.append((idx[0], fr))
    t = 0.0
    for q in seq:
        q["t0"], q["t1"] = t, t + q["dur"]
        t += q["dur"]
    return spans


def splice_words(spans, seq, words, c, ei, code, wi, pitch):
    """Overwrite the frames of each fitted callsign element with its whole-word unit."""
    q = vq()
    st = words["shape_bits"] == 18 and 2 or 4
    dw = int(round(127 * np.log10(pitch)))
    for i0, fr in spans:
        f0 = int(round(seq[i0]["t0"] / FRAME))
        # the pauses on either side are silent (no diphone tails into or out of the word)
        lo = f0 - (int(round(seq[i0 - 1]["dur"] / FRAME)) if i0 and seq[i0 - 1]["p"] == "PAU" else 0)
        i1 = next((i for i in range(i0, len(seq)) if seq[i]["p"] == "PAU"), len(seq))
        hi = f0 + len(fr) + (int(round(seq[i1]["dur"] / FRAME)) if i1 < len(seq) else 0)
        for f in range(max(0, lo), min(len(code), hi)):
            ei[f], code[f] = 0, 0
        for k, f in enumerate(fr):
            if 0 <= f0 + k < len(code):
                c[f0 + k] = sum(q.cb[s][f["si"][s]] for s in range(st))
                ei[f0 + k], code[f0 + k] = f["ei"], f["code"]
                wi[f0 + k] = min(127, max(0, f["wi"] + dw))


def synth_params(text, tab, rate=1.0, pitch=1.0, model=None, words="auto"):
    """Text -> sotto 1200 parameter dict (per 20 ms frame) and a report. model: None (the
    rules, the default: Jeff preferred them by ear on Luke 2), a prosody.Model, or "auto"
    (tts/data/prosody.bin). words: whole-word callsign units, "auto" (tts/data/words.stw if
    present) or None (callsigns from the table like any other word)."""
    import sotto_lr, vocoder_lab as vl
    if model == "auto":
        model = load_prosody()
    if model is not None:
        from . import prosody
        phrases = frontend.text_to_phrases(text)
        seq = prosody.phone_sequence(phrases)
        feats = prosody.features(seq)
        model.time(seq, rate, feats)
    else:
        seq, phrases = phone_plan(text, tab, rate)
    if words == "auto":
        words = load_words()
    spans = fit_words(seq, phrases, words) if words else []
    n = int(np.ceil(seq[-1]["t1"] / FRAME))
    n += n % 2
    if tab["kind"] == "robot":
        K, subs = keyframes_robot(seq, tab), 0
    else:
        K, subs = keyframes_diphone(seq, tab)
    c, ei, code = render(K, n)
    code = fix_voicing(code, ei)
    if model is not None:
        f0 = model.f0_track(seq, n, FRAME, pitch, feats)
    else:
        f0 = f0_track(seq, phrases, tab["f0"] * pitch, n)
    lr = sotto_lr.Sotto1200()
    wi = np.array([lr.wo_index(2 * np.pi * f / 8000) for f in f0])
    if spans:
        splice_words(spans, seq, words, c, ei, code, wi, pitch)
    shape = np.hstack([np.zeros((n, 1)), c]) @ vl.DCT
    p = dict(code=code, wi=wi, ei=np.clip(ei, 0, 31), shape=shape)
    rep = dict(phones=" ".join(q["p"] + (str(q["stress"]) if q["stress"] else "") for q in seq),
               seconds=n * FRAME, substitutions=subs)
    return p, rep


def fix_voicing(code, ei):
    """Silent frames unvoiced; an edge code (3) only next to an unvoiced frame."""
    code = code.copy()
    code[ei == 0] = 0
    for f in range(len(code)):
        if code[f] == 3:
            prev = code[f - 1] if f else 0
            nxt = code[f + 1] if f + 1 < len(code) else 0
            if prev != 0 and nxt != 0:
                code[f] = 2
    return code


def encode(p):
    import sotto_lr
    return sotto_lr.Sotto1200().encode_params(p)


def decode_c(bits, exe=None):
    """Superframe bits -> 8 kHz int16 samples with the fixed-point decoder the K6 runs (the
    v3.7 build from `make c37`; else c/'s, which gives the same sotto 1200 speech at 8 kHz)."""
    if exe is None:
        exe = os.path.join(ROOT, "build", "c37", "fixed", "sotto_dec_fx")
        if not os.path.exists(exe):
            exe = os.path.join(ROOT, "c", "fixed", "sotto_dec_fx")
    with tempfile.TemporaryDirectory() as d:
        np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(f"{d}/in.sot")
        subprocess.run([exe, "-1200", f"{d}/in.sot", f"{d}/out.raw"], check=True,
                       stdout=subprocess.DEVNULL)
        return np.fromfile(f"{d}/out.raw", "<i2")


def load_table(path):
    return T.read(open(path, "rb").read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text")
    ap.add_argument("--table", default=os.path.join(HERE, "data", "diphone.stt"))
    ap.add_argument("--wav")
    ap.add_argument("--sot", help="write the sotto 1200 superframes (6 bytes per 40 ms)")
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--pitch", type=float, default=1.0)
    ap.add_argument("--trained", action="store_true", help="the trained duration and pitch trees, not the rules")
    a = ap.parse_args()
    tab = load_table(a.table)
    p, rep = synth_params(a.text, tab, a.rate, a.pitch, "auto" if a.trained else None)
    bits = encode(p)
    print(rep["phones"])
    print(f"{rep['seconds']:.2f} s, {len(bits)} superframes ({6 * len(bits)} bytes), "
          f"{rep['substitutions']} stand-in diphones")
    if a.sot:
        np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(a.sot)
    if a.wav:
        import soundfile as sf
        sf.write(a.wav, decode_c(bits), 8000, subtype="PCM_16")


if __name__ == "__main__":
    main()
