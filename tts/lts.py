"""English letter-to-sound rules for sotto-tts.

The rule set follows the US Naval Research Laboratory report "Automatic Translation of English
Text to Phonetics by Means of Letter-to-Sound Rules" (Elovitz, Johnson, McHugh and Shore,
NRL Report 7948, 1976), a US Government work in the public domain, rewritten here for
ARPAbet phones with a few additions. Each rule is

    LEFT[MATCH]RIGHT=PHONES

and the first rule (in order, among those whose MATCH starts with the current letter) whose
three parts all fit is used. Context symbols:

    ' '  word edge            #  one or more vowels      :  zero or more consonants
    ^    one consonant        .  one voiced consonant    +  E, I or Y
    %    a suffix: ER E ES ED ING ELY (right context only)
    &    S C G Z X J CH SH (left context only)
    @    T S R D L Z N J TH CH SH (left context only)

Stress is not part of the rules: `stress()` guesses it afterwards from the word's shape.
SPDX-License-Identifier: MIT
"""
import re

RULES_TEXT = r"""
#A
 [A] =AX
 [ARE] =AA R
 [AR]O=AX R
[AR]#=EH R
^[AS]#=EY S
[A]WA=AX
[AW]=AO
[AIR]=EH R
[AI]=EY
[AY]=EY
 :[ANY]=EH N IY
[A]^+#=EY
#:[ALLY]=AX L IY
 [AL]#=AX L
[AGAIN]=AX G EH N
#:[AG]E=IH JH
[A]^+:#=AE
 :[A]^+ =EY
[A]^%=EY
 [ARR]=AX R
[ARR]=AE R
 :[AR] =AA R
[AR] =ER
[AR]=AA R
[AIR]=EH R
[AI]=EY
[AY]=EY
[AU]=AO
#:[AL] =AX L
#:[ALS] =AX L Z
[ALK]=AO K
[AL]^=AO L
 :[ABLE]=EY B AX L
[ABLE]=AX B AX L
[ANG]+=EY N JH
[A]=AE
#B
 [BE]^#=B IH
[BEING]=B IY IH NG
 [BOTH] =B OW TH
 [BUS]#=B IH Z
[BUIL]=B IH L
[B]=B
#C
 [CH]^=K
^E[CH]=K
[CH]=CH
 S[CI]#=S AY
[CI]A=SH
[CI]O=SH
[CI]EN=SH
[C]+=S
[CK]=K
[COM]%=K AH M
[C]=K
#D
#:[DED] =D IH D
.E[D] =D
#:^E[D] =T
 [DE]^#=D IH
 [DO] =D UW
 [DOES]=D AH Z
 [DOING]=D UW IH NG
 [DOW]=D AW
[D]G+=
[DU]A=JH UW
[D]=D
#E
#:[E] =
'^:[E] =
 :[E] =IY
#[ED] =D
#:[E]D =
[EV]ER=EH V
[E]^%=IY
[ERI]#=IY R IY
[ERI]=EH R IH
#:[ER]#=ER
[ER]#=EH R
[ER]=ER
 [EVEN]=IY V EH N
#:[E]W=
@[EW]=UW
[EW]=Y UW
[E]O=IY
#:&[ES] =IH Z
#:[E]S =
#:[ELY] =L IY
#:[EMENT]=M EH N T
[EFUL]=F UH L
[EE]=IY
[EARN]=ER N
 [EAR]^=ER
[EAD]=EH D
#:[EA] =IY AX
[EA]SU=EH
[EA]=IY
[EIGH]=EY
[EI]=IY
 [EYE]=AY
[EY]=IY
[EU]=Y UW
[E]=EH
#F
[FUL]=F UH L
[F]=F
#G
[GIV]=G IH V
 [G]I^=G
[GE]T=G EH
SU[GGES]=G JH EH S
[GG]=G
 B#[G]=G
[G]+=JH
[GREAT]=G R EY T
#[GH]=
[G]=G
#H
 [HAV]=HH AE V
 [HERE]=HH IY R
 [HOUR]=AW ER
[HOW]=HH AW
[H]#=HH
[H]=
#I
 [IN]=IH N
 [I] =AY
[IN]D=AY N
[IER]=IY ER
#:R[IED]=IY D
[IED] =AY D
[IEN]=IY EH N
[IE]T=AY EH
 :[I]%=AY
[I]%=IY
[IE]=IY
[I]^+:#=IH
[IR]#=AY R
[IZ]%=AY Z
[IS]%=AY Z
[I]D%=AY
+^[I]^+=IH
[I]T%=AY
#:^[I]^+=IH
[I]^+=AY
[IR]=ER
[IGH]=AY
[ILD]=AY L D
[IGN] =AY N
[IGN]^=AY N
[IGN]%=AY N
[IQUE]=IY K
[I]=IH
#J
[J]=JH
#K
 [K]N=
[K]=K
#L
[LO]C#=L OW
L[L]=
#:^[L]%=AX L
[LEAD]=L IY D
[L]=L
#M
[MOV]=M UW V
[M]=M
#N
E[NG]+=N JH
[NG]R=NG G
[NG]#=NG G
[NGL]%=NG G AX L
[NG]=NG
[NK]=NG K
 [NOW] =N AW
[N]=N
#O
[OF] =AX V
[OROUGH]=ER OW
#:[OR] =ER
#:[ORS] =ER Z
[OR]=AO R
 [ONE]=W AH N
[OW]=OW
 [OVER]=OW V ER
[OV]=AH V
[O]^%=OW
[O]^EN=OW
[O]^I#=OW
[OL]D=OW L
[OUGHT]=AO T
[OUGH]=AH F
 [OU]=AW
H[OU]S#=AW
[OUS]=AX S
[OUR]=AO R
[OULD]=UH D
^[OU]^L=AH
[OUP]=UW P
[OU]=AW
[OY]=OY
[OING]=OW IH NG
[OI]=OY
[OOR]=AO R
[OOK]=UH K
[OOD]=UH D
[OO]=UW
[O]E=OW
[O] =OW
[OA]=OW
 [ONLY]=OW N L IY
 [ONCE]=W AH N S
[ON'T]=OW N T
C[O]N=AA
[O]NG=AO
 :^[O]N=AH
I[ON]=AX N
#:[ON] =AX N
#^[ON]=AX N
[O]ST =OW
[OF]^=AO F
[OTHER]=AH DH ER
[OSS] =AO S
#:^[OM]=AH M
[O]=AA
#P
[PH]=F
[PEOP]=P IY P
[POW]=P AW
[PUT] =P UH T
[P]=P
#Q
[QUAR]=K W AO R
[QU]=K W
[Q]=K
#R
 [RE]^#=R IY
[R]=R
#S
[SH]=SH
#[SION]=ZH AX N
[SOME]=S AH M
#[SUR]#=ZH ER
[SUR]#=SH ER
#[SU]#=ZH UW
#[SSU]#=SH UW
#[SED] =Z D
#[S]#=Z
[SAID]=S EH D
^[SION]=SH AX N
[S]S=
.[S] =Z
#:.E[S] =Z
#:^##[S] =Z
#:^#[S] =S
U[S] =S
 :#[S] =Z
 [SCH]=S K
[S]C+=
#[SM]=Z M
#[SN]'=Z AX N
[S]=S
#T
 [THE] =DH AX
[TO] =T UW
[THAT] =DH AE T
 [THIS] =DH IH S
 [THEY]=DH EY
 [THERE]=DH EH R
[THER]=DH ER
[THEIR]=DH EH R
 [THAN] =DH AE N
 [THEM] =DH EH M
[THESE] =DH IY Z
 [THEN]=DH EH N
[THROUGH]=TH R UW
[THOSE]=DH OW Z
[THOUGH] =DH OW
 [THUS]=DH AH S
[TH]=TH
#:[TED] =T IH D
[TCH]=CH
S[TI]#N=CH
[TI]O=SH
[TI]A=SH
[TIEN]=SH AX N
[TUR]#=CH ER
[TU]A=CH UW
 [TWO]=T UW
[T]=T
#U
 [UN]I=Y UW N
 [UN]=AH N
 [UPON]=AX P AO N
@[UR]#=UH R
[UR]#=Y UH R
[UR]=ER
[U]^ =AH
[U]^^=AH
[UY]=AY
 G[U]#=
G[U]%=
G[U]#=W
#N[U]=Y UW
@[U]=UW
[U]=Y UW
#V
[VIEW]=V Y UW
[V]=V
#W
 [WERE]=W ER
[WA]S=W AA
[WA]T=W AA
[WHERE]=W EH R
[WHAT]=W AA T
[WHOL]=HH OW L
[WHO]=HH UW
[WH]=W
[WAR]=W AO R
[WOR]^=W ER
[WR]=R
[W]=W
#X
[X]=K S
#Y
[YOUNG]=Y AH NG
 [YOU]=Y UW
 [YES]=Y EH S
 [Y]=Y
#:^[Y] =IY
#:^[Y]I=IY
 :[Y] =AY
 :[Y]#=AY
 :[Y]^+:#=IH
 :[Y]^#=AY
[Y]=IH
#Z
[Z]=Z
"""

VOWEL_L = set("AEIOU")
CONS_L = set("BCDFGHJKLMNPQRSTVWXYZ")
VOICED_L = set("BDGJLMNRVWZ")
FRONT_L = set("EIY")
DOUBLE_SKIP = set("BDFGKLMNPRTVZ")


def _parse(text):
    rules = {}
    for line in text.strip().splitlines():
        if not line or line.startswith("#") and len(line) == 2:
            continue
        m = re.fullmatch(r"(.*)\[(.+)\](.*)=(.*)", line)
        if not m:
            raise ValueError(line)
        left, match, right, out = m.groups()
        rules.setdefault(match[0], []).append((left, match, right, out.split()))
    return rules


RULES = _parse(RULES_TEXT)


def _right(ctx, w, i):
    """Does right context ctx fit word w (padded with spaces) from index i?"""
    for k, c in enumerate(ctx):
        if c == "#":
            if i >= len(w) or w[i] not in VOWEL_L:
                return False
            while i < len(w) and w[i] in VOWEL_L:
                i += 1
        elif c == ":":
            while i < len(w) and w[i] in CONS_L:
                i += 1
        elif c == "^":
            if i >= len(w) or w[i] not in CONS_L:
                return False
            i += 1
        elif c == ".":
            if i >= len(w) or w[i] not in VOICED_L:
                return False
            i += 1
        elif c == "+":
            if i >= len(w) or w[i] not in FRONT_L:
                return False
            i += 1
        elif c == "%":
            for suf in ("ING", "ELY", "ER", "ES", "ED", "E"):
                if w.startswith(suf, i) and (i + len(suf) >= len(w) or not w[i + len(suf)].isalpha()):
                    return _right(ctx[k + 1:], w, i + len(suf))
            return False
        else:
            if i >= len(w) or w[i] != c:
                return False
            i += 1
    return True


def _left(ctx, w, i):
    """Does left context ctx fit word w ending just before index i (read right to left)?"""
    i -= 1
    for c in reversed(ctx):
        if c == "#":
            if i < 0 or w[i] not in VOWEL_L:
                return False
            while i >= 0 and w[i] in VOWEL_L:
                i -= 1
        elif c == ":":
            while i >= 0 and w[i] in CONS_L:
                i -= 1
        elif c == "^":
            if i < 0 or w[i] not in CONS_L:
                return False
            i -= 1
        elif c == ".":
            if i < 0 or w[i] not in VOICED_L:
                return False
            i -= 1
        elif c == "+":
            if i < 0 or w[i] not in FRONT_L:
                return False
            i -= 1
        elif c == "&":
            if i >= 1 and w[i - 1:i + 1] in ("CH", "SH"):
                i -= 2
            elif i >= 0 and w[i] in "SCGZXJ":
                i -= 1
            else:
                return False
        elif c == "@":
            if i >= 1 and w[i - 1:i + 1] in ("TH", "CH", "SH"):
                i -= 2
            elif i >= 0 and w[i] in "TSRDLZNJ":
                i -= 1
            else:
                return False
        else:
            if i < 0 or w[i] != c:
                return False
            i -= 1
    return True


def letters_to_phones(word):
    """One word (letters and apostrophes) -> ARPAbet phones without stress."""
    w = " " + word.upper() + " "
    i, out = 1, []
    while i < len(w) - 1:
        ch = w[i]
        if ch in DOUBLE_SKIP and w[i - 1] == ch:
            i += 1              # a doubled consonant letter sounds once
            continue
        for left, match, right, ph in RULES.get(ch, []):
            if w.startswith(match, i) and _left(left, w, i) and _right(right, w, i + len(match)):
                out += ph
                i += len(match)
                break
        else:
            i += 1              # a character no rule covers (apostrophe, digit): skip it
    return out


VOWEL_P = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY",
           "UH", "UW", "AX", "AXR"}
PREFIXES = ("A", "BE", "DE", "RE", "UN", "IN", "EX", "CON", "COM", "PRE", "DIS", "MIS", "TRANS")
SUFFIX_PRE = ("TION", "SION", "TIAN", "CIAN", "IC", "ICAL", "ITY", "IAL", "IAN", "IOUS", "EOUS")
SUFFIX_UN = ("ING", "ED", "ER", "ERS", "LY", "NESS", "MENT", "FUL", "LESS", "ES", "S", "EST")


def stress(word, ph):
    """Phones -> [(phone, stress)]: a guess of primary stress from the word's shape."""
    vi = [k for k, p in enumerate(ph) if p in VOWEL_P and p not in ("AX", "AXR")]
    vall = [k for k, p in enumerate(ph) if p in VOWEL_P]
    if not vall:
        return [(p, 0) for p in ph]
    w = word.upper()
    target = None
    if len(vall) >= 3:
        for suf in SUFFIX_PRE:
            if w.endswith(suf):
                n = sum(1 for c in suf if c in "AEIOU") - (1 if suf in ("TION", "SION", "TIAN", "CIAN", "IOUS", "EOUS") else 0)
                target = vall[max(0, len(vall) - 1 - n - 1)] if n >= 0 else None
                break
    if target is None and len(vall) >= 2:
        for pre in PREFIXES:
            if w.startswith(pre) and len(w) > len(pre) + 2:
                target = vall[1]
                break
    if target is None:
        target = vi[0] if vi else vall[0]
    out = []
    for k, p in enumerate(ph):
        s = 1 if k == target else 0
        if p == "AH" and s == 0:
            p = "AX"
        if p == "ER" and s == 0:
            p = "AXR"
        if p == "AX" and s:
            p = "AH"
        out.append((p, s))
    return out


def word_to_phones(word):
    return stress(word, letters_to_phones(word))
