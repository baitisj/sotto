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
| Units | 41 phones x 3 targets | 1,736 phone pairs, 3.9 frames each |
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

`tools/tts_corpus.py` has the Kokoro v1.0 model (Apache-2.0, Jeff's 11-16 pick, voice
af_heart) speak 49 minutes of text (768 utterances): 40 plain sentences, CMUdict words
picked greedily until every phone pair English needs occurs at least 6 times, and made-up
carrier words for the pairs that only occur across word boundaries. (A 25-minute corpus
with 3 instances per pair scored the same on sentences but worse on the callsign.) Kokoro is given phonemes, not
text, and one change to its ONNX graph (its duration predictor's output becomes a second
output) gives every phone's start and end exactly, with no forced aligner. The audio goes
through sotto 1200's own analysis. Two corrections:

- Kokoro's audio runs 50 ms ahead of its durations (measured on fricatives), and sotto's
  analysis frame centre is 12 ms before the frame time.
- Kokoro gives the silence next to a pause to the phone beside it (a phrase-final F ran 240
  ms). The build trims those edges to where the energy comes within 20 dB of the phone's
  peak.

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

- **Durations.** Each phone's median duration in the corpus, stressed and unstressed, is
  kept in the table (84 bytes). Function words are 0.85 times as long, and the last
  syllable of a phrase 1.35 times.
- **Pitch.** The voice's median pitch (188 Hz) falls 15% over each phrase. Each stressed
  content word gets a peak, each a little lower than the one before. A statement ends
  falling, a comma rises a little, and a yes/no question (starting with an auxiliary) ends
  rising. On the diphone table, flat pitch gives 46% word error against the rules' 33%
  (before joint selection), and Kokoro's own pitch and timing gave only 3 points better
  than the rules.

## Scores

Parakeet TDT 0.6B v2 (sherpa-onnx, int8) transcribes the output of the K6's fixed-point
sotto 1200 decoder (`build/c37/fixed/sotto_dec_fx`). Harvard sentences lists 1-3 (30
sentences, 240 words) are hard to guess from context, so they show acoustic errors. Numbers
and callsigns are compared in spoken form (`tools/tts_eval.py`).

| Word error | Harvard (240 words) | everyday (221) | radio (42) |
|---|---:|---:|---:|
| Kokoro af_heart, 8 kHz | 3.8% | 0.5% | 0.0% |
| Kokoro through sotto 1200 (the ceiling for these tables) | 5.0% | 1.4% | 2.4% |
| **diphone table** (37 KB) | 28.8% | **8.1%** | **9.5%** |
| diphone table, 18-bit shapes (23 KB) | 22.1% | 7.2% | 23.8% |
| **robotic table** (493 bytes) | 50.4% | 38.0% | 54.8% |

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
- **Synthesis:** front end, durations and pitch are a few hundred lines of integer code.
  The one heavy step is the codebook search: the prototype re-quantises the interpolated
  shapes with the reference encoder's search (`Sotto1200.encode_params`). On the K6 that
  is the slim encoder's search (`c/fixed/sotto_fx_slim.c`, about 150 SPI codebook reads per
  superframe), or none at all if the diphone frames' stored indices are copied straight
  into A frames and only B's 8-bit residual is searched (not tried yet).

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
python tools/tts_eval.py --asr PARAKEET_DIR [--ref-models MODELS]
```

## Next

- **Callsigns.** The NATO words are the weakest part of the demos: "Golf" comes out as
  "Gulf" and "Echo" is sometimes lost. More candidates per pair, or a few whole-word units for
  the 26 NATO words (about 2 KB), would fix that.
- **No re-quantisation on the K6:** copy stored indices and measure the cost.
- **A male voice** (Kokoro am_michael) for a second table, built the same way.
