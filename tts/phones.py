"""The phone set: ARPAbet's 39 phones, plus AX (unstressed AH) and AXR (unstressed ER), plus
the pause PAU. Stress is kept apart from the phone (0 none, 1 primary, 2 secondary).

KOKORO maps each phone to the phoneme symbols of the Kokoro v1.0 voices (American English,
misaki style); only the corpus builder uses it.
SPDX-License-Identifier: MIT
"""

VOWELS = ["AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY",
          "UH", "UW", "AX", "AXR"]
CONSONANTS = ["B", "CH", "D", "DH", "F", "G", "HH", "JH", "K", "L", "M", "N", "NG", "P",
              "R", "S", "SH", "T", "TH", "V", "W", "Y", "Z", "ZH"]
PAU = "PAU"
PHONES = [PAU] + VOWELS + CONSONANTS          # index = phone id (0 = pause)
ID = {p: i for i, p in enumerate(PHONES)}

STOPS = {"P", "B", "T", "D", "K", "G"}
AFFRICATES = {"CH", "JH"}
FRICATIVES = {"F", "V", "TH", "DH", "S", "Z", "SH", "ZH", "HH"}
NASALS = {"M", "N", "NG"}
LIQUIDS = {"L", "R", "W", "Y"}
DIPHTHONGS = {"AW", "AY", "EY", "OW", "OY"}
# The robot table's neighbour classes (tts/table.py): a phone's first target is picked by the
# class of the phone before it, its last target by the class of the phone after it.
CLASSES = ["PAU", "IY IH EY EH AE Y", "UW UH OW AO OY AW W", "AA AH AX ER AXR AY R",
           "P B M F V", "T D N S Z TH DH L", "SH ZH CH JH", "K G NG HH"]
CLASS = {p: c for c, ps in enumerate(CLASSES) for p in ps.split()}
VOICED_C = {"B", "D", "G", "JH", "V", "DH", "Z", "ZH", "M", "N", "NG", "L", "R", "W", "Y"}

KOKORO = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "W", "AY": "I", "EH": "ɛ", "ER": "ɜɹ",
    "EY": "A", "IH": "ɪ", "IY": "i", "OW": "O", "OY": "Y", "UH": "ʊ", "UW": "u", "AX": "ə",
    "AXR": "əɹ", "B": "b", "CH": "ʧ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h",
    "JH": "ʤ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ",
    "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z",
    "ZH": "ʒ",
}


def is_vowel(p):
    return p in VOWELS


def from_arpabet(sym):
    """'AH0' -> ('AX', 0), 'ER1' -> ('ER', 1), 'T' -> ('T', 0)."""
    if sym[-1].isdigit():
        base, st = sym[:-1], int(sym[-1])
    else:
        base, st = sym, 0
    if base == "AH" and st == 0:
        base = "AX"
    if base == "ER" and st == 0:
        base = "AXR"
    return base, st
