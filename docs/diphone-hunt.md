# Diphone hunt

How we find the rough patches in sotto-tts and in the sotto encoders: listen to every
diphone, flag the bad ones, track each one down to the cut or frame that made it, and fix
the cause. The process started by hand on 2026-11-21 with the af_sarah tables. The
`tools/diphone_hunt.py` generator and the `docs/diphone-hunt.html` bench automate it.

## The process, by hand (what Jeff did)

1. **Hear the whole space.** Render every diphone in the table back to back, with a 1 s
   pause every 5 s so time indexes are easy to call out. The af_sarah table (1,634 pairs) runs
   about 9 minutes. An index file maps each 5 s block to its pairs.
2. **Mark clusters, not single pairs.** Listening is fast but coarse: "something nasty around
   0:13 and 4:08". Each time index names a block of 10 to 20 pairs.
3. **Put the suspects into real words.** For every pair in a flagged block, pick a common
   English word that contains it (CMUdict + word frequency) and synthesise about 45 s of
   those words. In words the bad pairs stand out clearly ("cathy", "put", "tube", "ruin",
   "fluid", "January").
4. **Trace each bad word to its cause.** For each flagged pair, look at where the table cut
   it from (utterance, time) and at the frames:
   - IY-PAU cut from a spelled-out "P IY EY CH P IY" had its vowel frames coded unvoiced
     ("happy" came out as "cathy");
   - the T in "put" came from a cut with no stop closure;
   - UW in "tube", "ruin" and "fluid" came from the word "you", a cut that crossed a word
     boundary;
   - UW-EH ("January") has only 9 corpus instances, so there was no good choice.
5. **Fix the cause, not the pair.** Each cause became a build-time check in
   `tools/tts_build.py` (`checks()`): unvoiced frames inside a voiced half, loud stop
   closures, and cuts across words all add to a candidate's cost. The whole table gets
   rebuilt, so every pair with the same fault improves, not only the ones that were heard.
6. **A/B the words.** Old table vs new table on the flagged words, blind order, judged by ear.

What made this work: the ear finds faults quickly in bulk, real words confirm them, and
the source map turns a fault into a rule.

## The bench

`docs/diphone-hunt.html` gives every diphone its own row, so steps 1 to 4 happen on one page:

| Column | What it is | What it isolates |
|---|---|---|
| Reference | Kokoro says the word, 8 kHz | the target |
| Ref encoder | reference through sotto 1200 (sim/sotto_lr.py) and the K6 fixed-point decoder | what the encoder does |
| K6 slim | reference through `c/fixed/sotto_slim_enc` and the same decoder | what the K6's own encoder does |
| TTS | sotto-tts says the same phones from the table | what the table does |

The comparisons are Reference vs Ref encoder (or K6 slim) for encoder damage, and
Ref encoder vs TTS for table damage. Each clip carries a fingerprint, the first 8 hex
digits of the SHA-1 of its sotto bits. Two columns that share a fingerprint are the same
render, which catches mixed-up renders like the A/B mistakes in rounds 23 and 24.

Scores (per pair, over the span from the middle of the first phone to the middle of the
second):

- **table / codec / slim damage**: shape distance (dB RMS over the 19 DCT coefficients)
  plus energy steps, plus 2 for each of 6 points where voicing disagrees;
- **pitch**: reference frames where the sotto analysis pitch is more than 1.4x off pYIN
  (octave errors such as the foxtrot creak).

The page sorts by any score, filters by unheard, bad or fine, and searches by phone or word.
Keys: 1 to 4 play a column, Space replays, J and K (or the arrows) move between pairs, B marks
bad, G marks fine, N writes a note. Marks are saved with the artifact (collection `marks`,
one document per pair: verdict, which columns, note), so Claude can read them back and
start tracing without a transcript of time indexes.

## Making the data

    python tools/tts_build.py ... --sources OUT/sources.json   # where each diphone came from
    python tools/diphone_hunt.py --models KOKORO_DIR \
        --table tts/data/diphone.stt --sources OUT/sources.json \
        --out hunt --jobs 4

This writes `hunt/hunt.json` and `hunt/{ref,codec,slim,synth}.wav` (8 kHz G.711 mu-law, back to
back). Publish them next to `docs/diphone-hunt.html`. The af_sarah run takes about 25
minutes on 4 cores, and each WAV is about 11 MB.

## Using it for encoder work

The reference column does not change between runs, so the same 1,634 words make a fixed
test set for any encoder change. Rerun with the candidate encoder and sort by codec damage
or pitch: an encoder PR (pitch fix #194, envelope VQ) should lower the worst rows without
raising any others. Planned columns: the pitch torture set, a lossy channel (frame loss), the
page's own bitstream decoder, and a natural-speech reference (CMU ARCTIC) so the set no longer
depends on Kokoro.
