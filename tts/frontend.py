"""Text to phones for sotto-tts: normalisation, a small lexicon, letter-to-sound rules.

    phrases = frontend.text_to_phrases("This is AG7EW on 440.850 MHz.")

returns a list of phrases, each a dict with `words` (each: text, phones [(phone, stress)],
content flag) and `end` (the punctuation that closed it: '.', '?', '!' or ',').

Callsigns are always spoken in NATO phonetics ("AG7EW" -> Alpha Golf Seven Echo Whiskey).
Numbers with a decimal point are read digit by digit ("four four zero point eight five
zero"); whole numbers up to 9999 as words; longer ones digit by digit. Words are looked up in
tts/data/lexicon.txt (CMUdict pronunciations of the NATO words, digits, letter names, radio
words and the most frequent English words that the rules get wrong), then in tts.lts.
SPDX-License-Identifier: MIT
"""
import os, re
from . import lts
from .phones import from_arpabet

HERE = os.path.dirname(os.path.abspath(__file__))

NATO = {"A": "alfa", "B": "bravo", "C": "charlie", "D": "delta", "E": "echo", "F": "foxtrot",
        "G": "golf", "H": "hotel", "I": "india", "J": "juliett", "K": "kilo", "L": "lima",
        "M": "mike", "N": "november", "O": "oscar", "P": "papa", "Q": "quebec", "R": "romeo",
        "S": "sierra", "T": "tango", "U": "uniform", "V": "victor", "W": "whiskey",
        "X": "xray", "Y": "yankee", "Z": "zulu"}
DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
LETTER = {"A": "ay", "B": "bee", "C": "see", "D": "dee", "E": "ee", "F": "ef", "G": "gee",
          "H": "aitch", "I": "eye", "J": "jay", "K": "kay", "L": "el", "M": "em", "N": "en",
          "O": "oh", "P": "pee", "Q": "cue", "R": "ar", "S": "es", "T": "tee", "U": "you",
          "V": "vee", "W": "doubleyou", "X": "ex", "Y": "why", "Z": "zee"}
UNITS = {"mhz": ["megahertz"], "khz": ["kilohertz"], "hz": ["hertz"], "ghz": ["gigahertz"],
         "db": ["dee", "bee"], "dbm": ["dee", "bee", "em"], "w": ["watts"], "km": ["kilometers"],
         "utc": ["you", "tee", "see"], "pt": ["pacific"]}
FUNCTION = set("""a an the of to in on at by for from with as and or but nor so if than then
that this these those is am are was were be been being have has had do does did can could will
would shall should may might must i me my we us our you your he him his she her it its they
them their there here not no what which who whom whose when where how all any some each every
into onto up down out over off about just""".split())

CALLSIGN = re.compile(r"^[A-Za-z]{1,2}[0-9]{1,2}[A-Za-z]{1,4}(/[A-Za-z0-9]{1,4})?$")
DECIMAL = re.compile(r"^[0-9]+\.[0-9]+$")
INTEGER = re.compile(r"^[0-9]+$")

_LEX = None


def lexicon():
    global _LEX
    if _LEX is None:
        _LEX = {}
        path = os.path.join(HERE, "data", "lexicon.txt")
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(";") or not line.strip():
                    continue
                w, *ph = line.split()
                _LEX[w] = [from_arpabet(s) for s in ph]
    return _LEX


def cardinal(n):
    """0..9999 as words."""
    if n < 10:
        return [DIGITS[n]]
    if n < 20:
        return [TEENS[n - 10]]
    if n < 100:
        return [TENS[n // 10]] + ([DIGITS[n % 10]] if n % 10 else [])
    if n < 1000:
        return [DIGITS[n // 100], "hundred"] + (cardinal(n % 100) if n % 100 else [])
    if n % 1000 == 0:
        return cardinal(n // 1000) + ["thousand"]
    if 1100 <= n < 10000 and (n // 100) % 10:     # 1950 -> nineteen fifty
        hi, lo = divmod(n, 100)
        return cardinal(hi) + (["hundred"] if lo == 0 else (["oh"] if lo < 10 else []) + cardinal(lo))
    return cardinal(n // 1000) + ["thousand"] + cardinal(n % 1000)


def expand(token, prev=None):
    """One raw token -> list of (word, content) in spoken order."""
    t = token
    if CALLSIGN.match(t) and any(c.isdigit() for c in t):
        out = []
        for c in t.upper():
            if c.isdigit():
                out.append((DIGITS[int(c)], "spell"))
            elif c == "/":
                out.append(("stroke", "spell"))
            else:
                out.append((NATO[c], "spell"))
        return out
    if DECIMAL.match(t):
        a, b = t.split(".")
        return [(DIGITS[int(c)], True) for c in a] + [("point", True)] + \
               [(DIGITS[int(c)], True) for c in b]
    if INTEGER.match(t):
        n = int(t)
        if len(t) > 4 or t.startswith("0"):
            return [(DIGITS[int(c)], True) for c in t]
        return [(w, True) for w in cardinal(n)]
    low = t.lower()
    if low in UNITS and prev is not None and re.match(r"^[0-9.]+$", prev):
        return [(w, True) for w in UNITS[low]]
    if low in ("mhz", "khz", "ghz", "hz", "dbm", "utc"):
        return [(w, True) for w in UNITS[low]]
    if t.isupper() and 2 <= len(t) <= 5 and low not in lexicon() and t.isalpha():
        return [(LETTER[c], True) for c in t]       # an acronym: letter names
    if re.match(r"^[0-9]+[a-zA-Z]+$", t):            # 5W, 20m
        m = re.match(r"^([0-9]+)([a-zA-Z]+)$", t)
        return expand(m.group(1)) + expand(m.group(2), m.group(1))
    return [(low, low not in FUNCTION)]


def pronounce(word):
    lex = lexicon()
    if word in lex:
        return lex[word]
    w = re.sub(r"[^a-z']", "", word)
    if not w:
        return []
    if w in lex:
        return lex[w]
    return lts.word_to_phones(w)


def text_to_phrases(text):
    phrases, cur = [], []
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9./'-]*[A-Za-z0-9]|[A-Za-z0-9]|[.,?!;:]", text)
    prev = None
    for t in toks:
        if t in ".,?!;:":
            if cur:
                phrases.append(dict(words=cur, end={";": ",", ":": ","}.get(t, t)))
                cur = []
            continue
        t = t.rstrip(".")
        for part in t.split("-") if not CALLSIGN.match(t) else [t]:
            if not part:
                continue
            for w, content in expand(part, prev):
                ph = pronounce(w)
                if not content:         # function words: no stress, reduced vowels
                    ph = [({"AH": "AX", "ER": "AXR"}.get(p, p), 0) for p, _ in ph]
                if ph:
                    # "spell": a callsign element, said distinctly with a short gap after
                    cur.append(dict(text=w, phones=ph, content=bool(content),
                                    spell=content == "spell"))
            prev = part
    if cur:
        phrases.append(dict(words=cur, end="."))
    return phrases
