# sotto-tts: text to speech that speaks sotto frames

*2026-11-21. Prototype on the PC (`tts/`, `tools/tts_*.py`). Jeff asked whether a small
speech synthesiser that makes sotto frames could save space on the K6, and asked for two
versions: a small robotic phoneme table and a richer two-phone (diphone) table.*

## Idea

The K6 already carries a sotto 1200 decoder. A synthesiser therefore never has to make audio
itself. It only has to write a sotto parameter track, which per 20 ms frame is a voicing
code, a pitch, an energy and a spectral shape, and pack it into superframes. The decoder
does the rest.

- **The tables hold no pitch.** Pitch and timing come from rules, so the stored frames are
  only shape, energy and voicing. A 20 ms frame is 25 bits with a stages-1-2 shape (18 bits,
  what a sotto 1200 A frame carries) or 41 bits with the full v3.7 shape (34 bits).
- **Intonation comes almost free.** Pitch is its own field, so the synthesiser can raise a
  question, lengthen a phrase end or slow down without touching the units.
- **It says any text.** Callsigns are always spoken in NATO phonetics: "AG7EW" becomes
  Alfa Golf Seven Echo Whiskey.

## The two tables

| | robotic (`tts/data/robot.stt`) | diphone (`tts/data/diphone.stt`) |
|---|---:|---:|
| Units | 41 phones x 3 targets | 1,634 phone pairs, 4.1 frames each |
| Shape per frame | 18 bits | 34 bits |
| Size | **493 bytes** | **37 KB** (23 KB with 18-bit shapes) |
| Machine word error, everyday sentences | 38% | **8%** |
| Machine word error, Harvard sentences | 50% | 29% |

For scale, 37 KB is about 250 s of sotto 1200 speech (150 bytes a second): a fixed menu of
recorded prompts is smaller until it passes a few minutes. The synthesiser wins when the
text is open ended, such as callsigns, frequencies, times and messages.

- **Robotic.** Each phone has 3 targets (its start, middle and end). Each target is the
  average, over every instance of that phone in the corpus, of the envelope at that point,
  quantised to sotto's codebook. The synthesiser draws straight lines between all the
  targets in a phrase. Averaging the targets over every instance, instead of taking them
  from the phone's single most typical instance, cut machine word error from 80% to 51%.
- **Diphone.** Each phone pair is stored from the middle of the first phone to the middle
  of the second, so units join where phones are steadiest. The synthesiser places each
  half's frames at the same relative positions within its own (rule-timed) half phones.
  Where two units meet, each moves halfway towards the other, fading out towards the phone
  edges.
- **Choosing the diphones together.** Each pair has several candidate instances in the
  corpus. The build picks them jointly: a pair's choice minimises its duration mismatch
  plus the shape mismatch at both ends against the pairs it will meet there, weighted by how
  often English puts the three phones together (`tools/tts_build.py diphone_table`). This
  keeps allophones consistent, for example a coda L (as in "golf") matches the L of the L-F
  pair instead of an average L. On the 30 Harvard sentences it cut machine word error from 33% to 22%.

## Where the units come from

`tools/tts_corpus.py` has the Kokoro v1.0 model (Apache-2.0) speak the corpus. The voice is
af_sarah, Jeff's pick of the 28 English voices on 11-21 (`tools/tts_voices.py` renders them
all through sotto 1200). With `--sentences`, it first picks real sentences from a pool
(13,524 short sentences from the World English Bible, Luke left out for listening tests,
only common words) greedily, each scored by the phone pairs it adds per phone spoken, until
no sentence adds enough; CMUdict words (common ones first) and made-up carrier words then
fill the pairs still short of 6 instances. The Sarah corpus is 1,665 sentences and 387 lists,
122 minutes. (The first corpus, af_heart, was 49 minutes of mostly word lists read with
list intonation; on the Harvard sentences it scored 28.8% word error against Sarah's
15.4%.) `--reanalyse` redoes only the sotto analysis from the stored audio, for rebuilding
the tables after an encoder change. Kokoro is given phonemes, not
text, and one change to its ONNX graph (its duration predictor's output becomes a second
output) gives every phone's start and end exactly, with no forced aligner. The audio goes
through sotto 1200's own analysis. Two corrections:

- Kokoro's audio runs 50 ms ahead of its durations (measured on fricatives), and sotto's
  analysis frame centre is 12 ms before the frame time.
- Kokoro gives the silence next to a pause to the phone beside it (a phrase-final F ran 240
  ms). The build trims those edges to where the energy comes within 20 dB of the phone's
  peak.

## Callsign words

Callsign elements (NATO words, digits, "stroke") are not built from diphones. Each is a whole
recorded word (`tts/data/words.stw`, 37 words, 5 KB, `tools/tts_words.py`): Sarah reads it
slowly (speed 0.85) in the middle of "kilo. WORD, papa.", Kokoro's durations say where it
is, and the cut goes at the quietest frame near each end. (Said alone, words came out with
odd voiced onsets. At a comma Kokoro barely pauses, it lengthens the vowel instead, hence
the full stop before the word.) Each word keeps its own pitch, checked against pYIN, and is
stretched into the plan in place of its phones, with silence on either side; elements are
0.2 s apart. Diphone-built callsigns lost the vowel colour of short words ("golf" came out
"gulf") and ran together; with the words, callsign word error fell from 40% to 20%, most of
the rest being ordinary words around the callsign. The C synthesiser takes them with
`sotto_tts_set_words`; the CLI's `-nowords` leaves them out.

## Front end

`tts/frontend.py` and `tts/lts.py`:

- **Normalisation.** Callsigns become NATO words, with a short gap after each. Decimals are
  read digit by digit ("four four zero point eight five zero"). Whole numbers up to 9999 are
  read as words ("nineteen fifty"). MHz, kHz, dB and UTC are expanded, and other short
  all-capital words are spelled with letter names.
- **Letter-to-sound rules.** 313 rules in the format of the US Naval Research Laboratory's
  1976 report (Elovitz et al., NRL Report 7948, public domain), about 1.7 KB packed. Alone
  they get **77.6%** of running-text words exactly right (frequency weighted, against
  CMUdict).
- **Exception list.** `tts/data/lexicon.txt` holds CMUdict pronunciations (BSD licence) of
  the NATO words, numbers, letter names, radio words, and the words among the 2,000 most
  frequent English ones that the rules get wrong: 878 words, about 11.6 KB packed. With it,
  **92.9%** of words are exactly right (`tools/tts_lexicon.py`). Most remaining misses are
  vowel reductions such as AX against IH.
- **Stress** is guessed from prefixes and suffixes, and function words are unstressed.

## Prosody

By default durations and pitch come from rules (below). Two small regression trees are the
alternative (`--trained`, the page's Trained button). On Luke 2 Jeff preferred the rules by
ear, and the recogniser scores the two level, so the rules are the default.

The trees (`tts/prosody.py`,
`tts/data/prosody.bin`, 3.6 KB), trained by `tools/tts_prosody.py` on the same Kokoro voice
reading sentences: the Gospel of John and the first 600 verses of Acts (World English Bible,
1,477 verses, 172 minutes; Luke is kept out for listening tests). The 49-minute unit corpus is
mostly word lists read with list intonation, so it isn't used for this. Kokoro was given the
phones the front end makes, so its timings line up phone for phone with the synthesiser's own
plans.

- **Durations.** A 256-leaf tree predicts each phone's log duration from 28 features: the
  phone and its class, stress, content or function word, its place in the syllable, word and
  phrase, the classes of its neighbours, and the phrase type. Held-out error 0.26 (log)
  against 0.54 for one mean per corpus.
- **Pitch.** A 128-leaf tree predicts three log-pitch targets per vowel (20%, 50% and 80%
  through it, as a ratio to the voice's 191 Hz median) from 20 features: stress, accent
  counts before and after, the syllable's place in word and phrase, the phrase type and
  whether it is the last phrase. Held-out error 0.13 against 0.17. The pitch track is the
  sotto 1200 analysis's, with its subharmonic errors fixed first (5-10% of voiced frames,
  mostly at phrase ends, read at half or a third of the true pitch).
- **Pauses** are Kokoro's medians: 100 ms at a comma, 150 ms at a full stop, 80 ms between
  callsign elements.
- The trees were trained on af_heart, before the switch to Sarah; they still work, in
  ratios to the voice's median pitch, but were not retrained.
- **Yes/no questions** rise from the last accent to the end (x1.5). Kokoro reads its 49
  such questions in the corpus nearly level, so this one is a rule on top of the tree.
- Both trees walk with integer compares: each node is a feature number, a threshold and an
  offset (5 bytes), each leaf 1 or 3 values in 1/256 units.

The rules (the default; 84 bytes of durations in each table's header): each phone's corpus
median duration, stressed and unstressed, 15% slower than the corpus, function words 0.85
times as long and the phrase's last syllable 1.35 times; a pitch baseline from the voice's
median falling 15% over each phrase, a peak on each stressed content word (each a little
lower than the one before), and a final fall, a comma rise or a yes/no question rise. Flat pitch gives 46% word error against the
rules' 33% (before joint selection), so pitch matters to the recogniser.

## Scores

Parakeet TDT 0.6B v2 (sherpa-onnx, int8) transcribes the output of the K6's fixed-point
sotto 1200 decoder (`build/c37/fixed/sotto_dec_fx`). Harvard sentences lists 1-3 (30
sentences, 240 words) are hard to guess from context, so they show acoustic errors. Numbers
and callsigns are compared in spoken form (`tools/tts_eval.py`).

Sarah, tables rebuilt on the v3.10 encoder with the rough-patch checks (11-21 evening; rule prosody, with callsign words): diphone table 16.7% Harvard, 7.7% everyday, 0.0% radio, 17.6% calls; robot table 41.7%, 39.8%, 35.7%, 28.4%.

Sarah, first build (11-21, rule prosody, with callsign words; calls = 8 callsign phrases, 74 words):

| Word error | Harvard (240 words) | everyday (221) | radio (42) | calls (74) |
|---|---:|---:|---:|---:|
| Kokoro af_sarah, 8 kHz | 3.8% | 0.5% | 0.0% | 9.5% |
| Kokoro af_sarah through sotto 1200 | 4.6% | 0.5% | 0.0% | 12.2% |
| **diphone table** (36.6 KB) | **15.4%** | 9.5% | **9.5%** | **20.3%** |
| diphone table, callsigns from diphones | 15.4% | 9.5% | 11.9% | 40.5% |
| robotic table (493 bytes) | 45.8% | 34.8% | 23.8% | 25.7% |
| af_heart diphone table (before), callsigns from diphones | 28.8% | 8.1% | 14.3% | 35.1% |

The af_heart tables (11-21 morning), for the record:

| Word error | Harvard (240 words) | everyday (221) | radio (42) |
|---|---:|---:|---:|
| Kokoro af_heart, 8 kHz | 3.8% | 0.5% | 0.0% |
| Kokoro through sotto 1200 (the ceiling for these tables) | 5.0% | 1.4% | 2.4% |
| **diphone table** (37 KB) | 28.8% | **8.1%** | **9.5%** |
| diphone table, 18-bit shapes (23 KB) | 22.1% | 7.2% | 23.8% |
| **robotic table** (493 bytes) | 50.4% | 38.0% | 54.8% |
| diphone table, trained prosody | 25.0% | 13.6% | 21.4% |
| robotic table, trained prosody | 65.4% | 45.2% | 66.7% |

The rows above the last two use the rule prosody. Over all 503 words the trained trees and
the rules are level on the diphone table (99 and 91 errors; trees with rule pitch 105, rules
with tree pitch 101, trees with their pitch swings made 1.5 times wider 94), and the
recogniser's mistakes move from sentence to sentence rather than shrinking. The spectral
shapes are what limit it (below). By ear (Jeff, Luke 2) the rules sound better, so they stay
the default.

With 503 words in all, the two diphone tables are level (18% and 16%); differences of a
few points between runs are noise. The 34-bit table is the default because it said the
callsign better. The recogniser's own guesses on the demo phrases (diphone table): "The
quick brown fox jumps over the lazy dog.", "The frequency is 440.850 MHz.", "Is the repeater
on the air tonight?", "Battery low. Please charge the radio.", "This is Alpha Gulf 7 egg of
whiskey." The robotic table: "The quick brown fox jumps over the lazy dog.", "Total can say
any text, even words it have never heard before."

Swapping parts of Kokoro's own sotto parameters for the synthesiser's shows where the loss
is: its shapes alone take word error from 4.6% to 35% (before joint selection), while its
energy (8.8%) and voicing (7.1%) cost little.

## On the K6

- **Decoder:** already on the radio.
- **Tables:** robot.stt fits in RAM. diphone.stt, lexicon and rules belong in the SPI
  module library as data decks.
- **Synthesis:** `c/tts/sotto_tts.c` (below); the prosody trees are 3.6 KB of integer
  compares.
  The one heavy step is the codebook search: the prototype re-quantises the interpolated
  shapes with the reference encoder's search (`Sotto1200.encode_params`). On the K6 that
  is the slim encoder's search (`c/fixed/sotto_fx_slim.c`, about 150 SPI codebook reads per
  superframe), or none at all if the diphone frames' stored indices are copied straight
  into A frames and only B's 8-bit residual is searched (not tried yet).

## In C, and on a web page

`c/tts/sotto_tts.c` is the synthesiser in C (about 1,100 lines, C99): the front end, the
letter-to-sound rules, the lexicon, the prosody trees, both tables, keyframes and frames. It
hands each 20 ms frame to the K6's fixed-point sotto 1200 coder (`sotto_lr_enc_push` in
`c/fixed/sotto_fx_lr_enc.c`), so the superframes are what the radio would send. The data
(rules, lexicon, tables, trees) is linked in from `c/tts/sotto_tts_data.c`, which
`tools/tts_cdata.py` writes from `tts/`.

- **Same as Python.** `tools/tts_ccheck.py` runs both on ten test sentences: phones, voicing,
  pitch and energy codes match exactly, shapes to 0.002 dB (C reads the fixed-point codebook).
  The front end gives the same words and phones on the 6,000 most frequent English words.
  Both prosodies (rules and trees) are ported and checked. The
  superframes differ only where the fixed-point and float coders pick differently between
  near-equal shapes (a few in a hundred).
- **Same as the radio.** `sotto_tts -pcm` decodes with the fixed-point decoder; its samples
  are identical to `build/c37/fixed/sotto_dec_fx -1200`'s.
- **Web page.** `docs/tts.html` with `docs/sotto_tts.wasm` (205 KB: the code, both tables,
  the lexicon and rules, the trees, the fixed-point codebook, coder and decoder). Type text,
  pick the table, the prosody (rules or trained), rate and pitch, and it plays the decoded speech, highlighting each word,
  with the superframes shown in hex. `node c/wasm/check_tts.mjs` checks the module against
  the native tool (same superframes, same samples).

The synthesis itself is still floating point (interpolation, `exp` for the trees' log
durations and pitch); on the K6 those become a few integer tables.

```sh
make -C c/tts                          # sotto_tts: text -> .sot, -pcm for 8 kHz samples
c/tts/sotto_tts -pcm out.raw "This is AG7EW." out.sot
python tools/tts_ccheck.py [--robot] [--trained]   # C against Python
make -C c/wasm install-tts check-tts   # docs/sotto_tts.wasm and its check (clang, wasm-ld, wasi-libc)
```

## Use

```sh
make && make c37                       # the decoders
python -m tts.synth "This is AG7EW." --table tts/data/diphone.stt --wav out.wav --sot out.sot
python tools/tts_demo.py OUTDIR        # the demo phrases, both tables

# rebuilding the tables (needs onnx, onnxruntime, cmudict, wordfreq, kokoro-onnx's config)
sh ../blowfang/tools/tts_models.sh MODELS          # Kokoro v1.0 from GitHub releases
python tools/tts_corpus.py --models MODELS --out corpus.npz
python tools/tts_build.py corpus.npz
python tools/tts_lexicon.py
python tools/tts_eval.py --asr PARAKEET_DIR [--ref-models MODELS] [--prosody trees rules]
python tools/tts_prosody.py corpus --models MODELS --out prosody_corpus.pkl   # 40 min
python tools/tts_prosody.py train prosody_corpus.pkl                         # tts/data/prosody.bin
python tools/tts_cdata.py                                                     # c/tts/sotto_tts_data.c
```

## Next

- **Callsigns.** The NATO words are the weakest part of the demos: "Golf" comes out as
  "Gulf" and "Echo" is sometimes lost. More candidates per pair, or a few whole-word units for
  the 26 NATO words (about 2 KB), would fix that.
- **No re-quantisation on the K6:** copy stored indices and measure the cost.
- **A male voice** (Kokoro am_michael) for a second table, built the same way.
