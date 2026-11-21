---
title: "2. From letters to sounds"
---

# 2. From letters to sounds

Previous: [Talking in frames](01-talking-in-frames.md) · [Course home](README.md) · Next: [Sounds in pairs: diphones](03-diphones.md)

## Big idea

English spelling is a mess. "Night" and "knight" sound the same; "said" doesn't rhyme with "paid". Before sotto-tts can say anything, it has to turn the text into a list of **phones**, the separate sounds of speech. This part of the engine is called the **front end**. It works in three steps: tidy the text into plain words, sound out each word with rules, and look up the words the rules get wrong.

## Step 1: tidy the text (normalisation)

Text has things in it that aren't words: numbers, callsigns, units, abbreviations. Turning them into words is called **normalisation**. Here is what the front end does with some radio text:

| You type | sotto-tts says |
|---|---|
| `AG7EW` | alfa golf seven echo whiskey |
| `KD7ABC/P` | kilo delta seven alfa bravo charlie stroke papa |
| `440.850` | four four zero point eight five zero |
| `1950` | nineteen fifty |
| `MHz` | megahertz |
| `UTC` | you tee see |

- **Callsigns** are spoken in the **NATO phonetic alphabet** (Alfa, Bravo, Charlie...), the way radio operators say them, so that letters like B, D, E and P can't be confused. Each word is said clearly, with a 0.2 s gap after it. The front end spots a callsign by its pattern: letters, a digit, then more letters.
- sotto-tts uses the pronunciations from the official ICAO list: **Lima** is *LEE-ma* (not *LY-ma*, like the bean) and **Kilo** is *KEE-loh*.
- **Decimals** are read digit by digit, because that's how frequencies are read on the air. **Whole numbers** up to 9,999 are read as words.
- **Short all-capital words** that aren't in the dictionary are spelled out with letter names.

## Step 2: phones

A **phone** is one speech sound. English has about 40 of them, and sotto-tts uses 41, written in **ARPAbet** (say *AR-puh-bet*), a way of spelling sounds with plain capital letters. A few examples:

| Phone | As in | Phone | As in | Phone | As in |
|---|---|---|---|---|---|
| AA | f**a**ther | IY | s**ee** | SH | **sh**ip |
| AE | c**a**t | UW | f**oo**d | CH | **ch**ip |
| AH | c**u**t | AY | n**igh**t | TH | **th**in |
| AX | **a**bout (a quick "uh") | OW | g**o** | DH | **th**is |
| EH | b**e**d | ER | b**ir**d | NG | si**ng** |
| IH | b**i**t | EY | c**a**ke | ZH | mea**s**ure |

There is also **PAU**, a pause. A number after a vowel marks **stress**: 1 is the strongest syllable of the word, 2 a weaker one, and no number means unstressed. So "golf" is `G AA1 L F` and "alfa" is `AE1 L F AX`.

Why not just use letters? Because the same letter makes different sounds ("c" in "cat" and "city"), and the same sound has different spellings ("f" in "phone" and "laugh"). Phones remove that confusion: one symbol, one sound.

## Step 3: letter-to-sound rules

To sound out a word it has never seen, sotto-tts uses **letter-to-sound rules**. They follow a 1976 report by the US Naval Research Laboratory (NRL Report 7948), which is public domain. Each rule looks like this:

```
LEFT[MATCH]RIGHT=PHONES
```

It means: "if you find the letters MATCH, with LEFT just before them and RIGHT just after them, say PHONES." The engine walks along the word from left to right. At each letter it tries the rules for that letter **in order** and uses the first one that fits. Some real rules:

| Rule | Meaning | Example |
|---|---|---|
| `[IGH]=AY` | "igh" says AY | n**igh**t |
| `#[GH]=` | "gh" after a vowel is silent | thou**gh** |
| ` [CH]^=K` | "ch" at the start of a word, before a consonant, says K | **ch**rome |
| `[CH]=CH` | otherwise "ch" says CH | **ch**ip |
| `#:[E] =` | a final "e" after a vowel and some consonants is silent | cak**e** |
| `[A]=AE` | if nothing else fits, "a" says AE | c**a**t |

The special symbols in LEFT and RIGHT stand for groups of letters: a space is the edge of the word, `#` is one or more vowels, `^` is one consonant, and `:` is any number of consonants (even none). Because the more specific rules come first, the last rule for each letter is the "if nothing else fits" sound.

sotto-tts has **313 rules**, which pack into about 1.7 KB. On their own they get **77.6%** of the words in ordinary text exactly right (counting common words more, because they come up more often).

## Step 4: the exceptions list

The rules get the commonest words wrong surprisingly often: "one", "two", "women", "said", "radio". So sotto-tts also keeps an **exceptions list** (a *lexicon*, say *LEK-si-kon*). It holds the pronunciations, from the free CMU Pronouncing Dictionary, of:

- the NATO words, numbers and letter names,
- radio words,
- every word among the 2,000 most common English words that the rules get wrong.

That is 878 words, about 11.6 KB packed. With the list, **92.9%** of words come out exactly right. The front end looks a word up first, and only uses the rules if it isn't there.

| Word | Rules say | Right answer | |
|---|---|---|---|
| night | N AY1 T | N AY1 T | rules are right |
| women | W OW1 M EH N | W IH1 M AX N | in the list, so fixed |
| radio | R EY1 D IH OW | R EY1 D IY OW2 | in the list, so fixed |
| juice | JH UW1 AY S | JH UW1 S | not in the list: wrong |
| sugar | S UW1 G AXR | SH UH1 G AXR | not in the list: wrong |

The last two are real mistakes the engine still makes. A longer list (the 5,000 commonest words would take about 36 KB) would fix most of them.

## Stress and small words

The rules don't say which syllable is stressed, so a small function guesses it from the shape of the word (prefixes like "re-" and suffixes like "-tion" are clues). And **function words**, the little words like "the", "is", "of" and "to", get no stress at all, and their vowels become the quick AX sound, the way people really say them: "the" is `DH AX`, not "thee".

## Try it

1. Write the ARPAbet phones for "ship", "chip" and "thin" using the table above.
2. How would the front end say the callsign `W1AW`? And the frequency `146.520`?
3. The rules say "juice" is `JH UW1 AY S`. Which letters do you think the rules turned into `AY`? Why might that be?
4. If the rules get 77.6% of words right and the list fixes the rest up to 92.9%, what fraction of the rules' mistakes does the list fix?

## Where this is in the code

- `tts/frontend.py`: `text_to_phrases()` (normalisation and phrases), `expand()` (numbers, callsigns, units), `pronounce()` (lexicon first, then rules).
- `tts/lts.py`: the 313 rules (`RULES_TEXT`), `letters_to_phones()` and `stress()`.
- `tts/data/lexicon.txt`: the exceptions list; `tools/tts_lexicon.py` chooses which words go in it.

<details markdown="1"><summary>Answers</summary>

1. "ship" is `SH IH1 P`, "chip" is `CH IH1 P`, "thin" is `TH IH1 N`. One-syllable words still get stress 1 on their vowel.
2. `W1AW` is "whiskey one alfa whiskey". `146.520` is "one four six point five two zero".
3. The "i" in "ui". In words like "fine" and "like", an "i" before a consonant and a final "e" says AY, and the rules don't know that "ui" in "juice" is a single vowel sound.
4. The rules get 22.4% wrong; the list brings that down to 7.1%. It fixes (22.4 − 7.1) ÷ 22.4 ≈ 68%, about two thirds, of the mistakes.

</details>
