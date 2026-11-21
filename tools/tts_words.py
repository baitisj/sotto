#!/usr/bin/env python3
"""Build tts/data/words.stw: whole-word units for spelling callsigns.

    python tools/tts_words.py --models KOKORO_DIR [--speed 0.85] [--shape-bits 34]

Kokoro (af_sarah) reads each NATO word, each digit and "stroke" slowly (speed 0.85) in the
middle of a short spelled list ("kilo. WORD, papa."), from the phones tts.frontend gives it.
A word said on its own came out with odd voiced onsets; in a list it gets the level, careful
reading of a callsign element; the full stop after "kilo" leaves a real pause before it
(Kokoro barely pauses at a comma, it lengthens the vowel instead).
Kokoro's duration output says exactly where the word starts and ends. The whole list is
analysed as sotto 1200 analyses speech (per 20 ms: voicing, pitch, energy, shape), the
word's frames are cut out and trimmed to its sound, voiced pitch is checked against pYIN
(an octave or fifth off is replaced; frames still far from the word's median are held or
made unvoiced), and the word is stored with its own pitch
(tts/table.py, write_words). The synthesiser splices these in for callsign
elements instead of building them from diphones, which made "Golf" sound like "Gulf".
SPDX-License-Identifier: MIT
"""
import argparse, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]
from tts import frontend, table  # noqa: E402

WORDS = list(frontend.NATO.values()) + frontend.DIGITS + ["stroke"]


CARRIER = ("kilo", "papa")


def pyin_f0(x8):
    """pYIN pitch per 20 ms frame (Hz, 0 when unvoiced), on the sotto frame grid."""
    import librosa
    f, v, _ = librosa.pyin(x8.astype(np.float32), fmin=70, fmax=500, sr=8000,
                           frame_length=512, hop_length=160, center=True)
    return np.where(v, np.nan_to_num(f), 0.0)


def fix_pitch(p, k0, k1, ref, lr):
    """Voiced frames whose pitch is an octave or a fifth away from pYIN get pYIN's."""
    import vocoder_lab as vl
    n = 0
    for k in range(k0, k1):
        if p["code"][k] == 0 or k >= len(ref) or ref[k] <= 0:
            continue
        f = lr.wo_value(p["wi"][k]) * 8000 / (2 * np.pi)
        if abs(np.log2(f / ref[k])) > 0.4:
            wo = 2 * np.pi * ref[k] / 8000
            p["wi"][k] = int(vl.q_wo(np.array([wo]), hi=lr.WO_HI)[0][0])
            n += 1
    return n


def hold_pitch(p, a, b):
    """Within the word, a voiced frame far below or above the word's median pitch (a creaky
    or subharmonic tail, as "foxtrot" ended an octave down) is made unvoiced when it is quiet
    (a release or fade, 8+ energy steps under the word's peak), else given the pitch of the
    nearest frame that is in range."""
    v = [k for k in range(a, b) if p["code"][k]]
    if not v:
        return 0
    med = np.median([p["wi"][k] for k in v])
    span = 127 * np.log10(1.4)                     # x1.4 in pitch-index steps
    ok = [k for k in v if abs(p["wi"][k] - med) <= span]
    top = max(p["ei"][a:b])
    n = 0
    for k in v:
        if abs(p["wi"][k] - med) <= span:
            continue
        if p["ei"][k] <= top - 8 or not ok:
            p["code"][k] = 0
        else:
            p["wi"][k] = p["wi"][min(ok, key=lambda j: abs(j - k))]
        n += 1
    return n


def analyse_word(x8, quant, shape_bits, span=None):
    """Frames of the word in x8 (the whole of x8, or the (start, end) span in seconds)."""
    import sotto_lr, vocoder_lab as vl
    lr = sotto_lr.Sotto1200()
    p = lr.params(x8)
    k0, k1 = 0, len(p["ei"])
    if span:
        # Kokoro's phone times are good to a frame or two; the word starts and ends at the
        # quietest frame near them (the pause after "kilo.", the closure before "papa")
        e = p["ei"]
        s0 = int(round(span[0] / 0.02))
        s1 = int(round(span[1] / 0.02))
        w0 = np.arange(max(0, s0 - 3), min(len(e), s0 + 2))
        w1 = np.arange(max(0, s1 - 1), min(len(e), s1 + 4))
        k0 = int(w0[np.argmin(e[w0])])
        k1 = int(w1[np.argmin(e[w1])]) + 1
    nfix = fix_pitch(p, k0, k1, pyin_f0(x8), lr)
    on = k0 + np.flatnonzero(p["ei"][k0:k1] > 0)
    a, b = max(k0, on[0] - 1), min(k1, on[-1] + 2)
    nfix += hold_pitch(p, a, b)
    c = (p["shape"][a:b] @ vl.DCT.T)[:, 1:]
    si = quant.search(c, shape_bits)
    return [dict(code=int(p["code"][k]), wi=int(p["wi"][k]), ei=int(p["ei"][k]),
                 si=[int(v) for v in si[k - a]]) for k in range(a, b)], nfix


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True)
    ap.add_argument("--voice", default="af_sarah")
    ap.add_argument("--alone", action="store_true", help="say each word on its own (old way)")
    ap.add_argument("--wavs", help="also write each cut word as an 8 kHz WAV here")
    ap.add_argument("--speed", type=float, default=0.85)
    ap.add_argument("--shape-bits", type=int, default=34, choices=[18, 34])
    ap.add_argument("--out", default=os.path.join(ROOT, "tts", "data", "words.stw"))
    a = ap.parse_args()
    import tts_corpus, tts_build
    from scipy.signal import resample_poly
    kok = tts_corpus.Kokoro(a.models, a.voice)
    quant = tts_build.Quant()
    words = {}
    for w in WORDS:
        if a.alone:
            y, _ = kok.say([(frontend.pronounce(w), ".")], speed=a.speed)
            span = None
        else:
            utt = [(frontend.pronounce(CARRIER[0]), "."), (frontend.pronounce(w), ","),
                   (frontend.pronounce(CARRIER[1]), ".")]
            y, segs = kok.say(utt, speed=a.speed)
            mine = [s for s in segs if s[2] == 1]
            span = (mine[0][3], mine[-1][4])
        x8 = tts_corpus.level(resample_poly(y, 1, 3)).astype(np.float64)
        words[w], nfix = analyse_word(x8, quant, a.shape_bits, span)
        if a.wavs:
            import soundfile as sf
            os.makedirs(a.wavs, exist_ok=True)
            i0 = int(span[0] * 8000) - 400 if span else 0
            i1 = int(span[1] * 8000) + 400 if span else len(x8)
            sf.write(os.path.join(a.wavs, w + ".wav"), x8[i0:i1] / 32768 if abs(x8).max() > 2 else x8[i0:i1], 8000)
        print(f"{w:10s} {len(words[w]) * 0.02:.2f} s  pitch fixed {nfix}", flush=True)
    raw = table.write_words(a.shape_bits, words)
    open(a.out, "wb").write(raw)
    print(f"{a.out}: {len(words)} words, {sum(len(v) for v in words.values())} frames, {len(raw)} bytes")


if __name__ == "__main__":
    main()
