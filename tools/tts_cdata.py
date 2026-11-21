#!/usr/bin/env python3
"""Write c/tts/sotto_tts_data.c: sotto-tts's data for the C synthesiser (c/tts/sotto_tts.c).

    python tools/tts_cdata.py [--out c/tts/sotto_tts_data.c] [--check]

From tts/: the letter-to-sound rules (tts/lts.py RULES_TEXT), the lexicon
(tts/data/lexicon.txt, CMUdict notice kept), the robot and diphone tables, the prosody trees, the whole-word callsign units,
as C arrays.
SPDX-License-Identifier: MIT
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tts import lts  # noqa: E402


def c_string(name, text):
    out = [f"const char {name}[] ="]
    for line in text.splitlines(True):
        esc = line.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        out.append(f'  "{esc}"')
    return "\n".join(out) + ";\n"


def c_bytes(name, data):
    rows = [", ".join(str(b) for b in data[i:i + 24]) for i in range(0, len(data), 24)]
    return (f"const unsigned {name}_len = {len(data)};\n"
            f"const unsigned char {name}[] = {{\n  " + ",\n  ".join(rows) + "\n};\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "c", "tts", "sotto_tts_data.c"))
    ap.add_argument("--check", action="store_true", help="only check that --out is up to date")
    a = ap.parse_args()
    D = os.path.join(ROOT, "tts", "data")
    lex = open(os.path.join(D, "lexicon.txt")).read()
    src = ["/* sotto-tts data, written by tools/tts_cdata.py from tts/ (do not edit).",
           " * The rules: NRL Report 7948 (public domain) as rewritten in tts/lts.py. The lexicon:",
           " * pronunciations from the CMU Pronouncing Dictionary, Copyright (C) 1993-2015 Carnegie",
           " * Mellon University, used under its BSD-style licence (notice in the lexicon below).",
           " * SPDX-License-Identifier: MIT */",
           "#include \"sotto_tts.h\"", "",
           c_string("sotto_tts_rules", lts.RULES_TEXT.strip() + "\n"),
           c_string("sotto_tts_lexicon", lex)]
    for name, f in (("sotto_tts_robot", "robot.stt"), ("sotto_tts_diphone", "diphone.stt"),
                    ("sotto_tts_prosody", "prosody.bin"), ("sotto_tts_wordunits", "words.stw")):
        src.append(c_bytes(name, open(os.path.join(D, f), "rb").read()))
    text = "\n".join(src)
    if a.check:
        ok = os.path.exists(a.out) and open(a.out).read() == text
        print(a.out, "is up to date" if ok else "is out of date: run python tools/tts_cdata.py")
        return 0 if ok else 1
    open(a.out, "w").write(text)
    print(a.out, os.path.getsize(a.out), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
