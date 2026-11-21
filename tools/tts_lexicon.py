#!/usr/bin/env python3
"""Write tts/data/lexicon.txt: the words sotto-tts looks up before its letter-to-sound rules.

It holds CMUdict pronunciations (CMUdict is BSD-licensed; see the notice at the top of the
file) of: the NATO alphabet, number words, letter names and some radio words, plus every word
among the N most frequent English words (wordfreq's list) that tts.lts gets wrong.

    python tools/tts_lexicon.py [--top 2000]

Needs cmudict and wordfreq (pip). Prints how much of running English text the rules get
right with and without the list.
SPDX-License-Identifier: MIT
"""
import argparse, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tts import lts, frontend as F, phones as P  # noqa: E402

# Spellings CMUdict lacks or gets wrong for our use (ARPAbet with stress)
MANUAL = {
    "alfa": "AE1 L F AH0", "juliett": "JH UW1 L IY0 EH2 T", "xray": "EH1 K S R EY2",
    "niner": "N AY1 N ER0", "ay": "EY1", "ee": "IY1", "ar": "AA1 R", "es": "EH1 S",
    "doubleyou": "D AH1 B AH0 L Y UW0", "el": "EH1 L", "em": "EH1 M", "en": "EH1 N",
    "ef": "EH1 F", "aitch": "EY1 CH", "stroke": "S T R OW1 K", "sotto": "S AA1 T OW0",
    "fusotto": "F Y UW1 S AA2 T OW0", "blowfang": "B L OW1 F AE2 NG",
    "kilohertz": "K IH1 L AH0 HH ER2 T S", "gigahertz": "G IH1 G AH0 HH ER2 T S",
    # the ICAO sounds (Jeff 11-21: LEE-ma, not CMUdict's LY-ma), KEE-loh, FOKS-trot
    "lima": "L IY1 M AH0", "kilo": "K IY1 L OW2", "foxtrot": "F AA1 K S T R AA2 T",
}
RADIO = """repeater frequency megahertz kilohertz gigahertz hertz watts test testing over out
roger copy station signal battery low channel transmit transmitting receive receiving mode
volume squelch scan power call calling clear standby stand by minutes hours message messages
weather alert warning simplex duplex offset tone antenna radio amateur pacific time point
oh hundred thousand stroke please repeat say again""".split()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=2000)
    ap.add_argument("--out", default=os.path.join(ROOT, "tts", "data", "lexicon.txt"))
    a = ap.parse_args()
    import cmudict, wordfreq
    d = cmudict.dict()
    want = list(F.NATO.values()) + F.DIGITS + F.TEENS + [t for t in F.TENS if t] + \
        list(F.LETTER.values()) + [w for v in F.UNITS.values() for w in v] + RADIO
    lex = {}
    for w in want:
        if w in MANUAL:
            lex[w] = MANUAL[w]
        elif w in d:
            lex[w] = " ".join(d[w][0])
        else:
            raise SystemExit(f"no pronunciation for {w}")
    lex.update(MANUAL)
    top = [w for w in wordfreq.top_n_list("en", 4 * a.top) if w.isalpha() and w in d][:20000]
    fr = np.array([wordfreq.word_frequency(w, "en") for w in top])

    def rules_ok(w):
        hyp = [p for p, _ in lts.word_to_phones(w)]
        return any(hyp == [P.from_arpabet(s)[0] for s in r] for r in d[w])
    ok = np.array([rules_ok(w) for w in top])
    n_exc = 0
    for w, o in zip(top[:a.top], ok[:a.top]):
        if not o and w not in lex:
            lex[w] = " ".join(d[w][0])
            n_exc += 1
    inlex = np.array([w in lex for w in top])
    print(f"running text (top {len(top)} words, frequency weighted): rules alone "
          f"{100 * (fr * ok).sum() / fr.sum():.1f}% of words exact, with the lexicon "
          f"{100 * (fr * (ok | inlex)).sum() / fr.sum():.1f}%")
    with open(a.out, "w") as f:
        f.write("; sotto-tts lexicon, written by tools/tts_lexicon.py. Pronunciations from the CMU\n"
                "; Pronouncing Dictionary, Copyright (C) 1993-2015 Carnegie Mellon University, used\n"
                "; under its BSD-style licence (redistribution with this notice permitted).\n")
        for w in sorted(lex):
            f.write(f"{w} {lex[w]}\n")
    size = sum(len(w) + 1 + len(v.split()) for w, v in lex.items())
    print(f"{len(lex)} words ({n_exc} rule exceptions), about {size} bytes packed "
          f"(a byte per letter and per phone)")


if __name__ == "__main__":
    main()
