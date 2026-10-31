# Listening tests: the blind A/B platform

PESQ and ESTOI choose between codec structures, but they have been wrong about things that
matter on the air. In round 7, concealment that scored higher sounded worse. In rounds 3 and
4, a codec that "fixed" a thin microphone was preferred over a faithful one. So every change
that affects the sound goes through a blind A/B round with Jeff (and others in his radio club)
before it becomes the default. This page describes how a round works, so a new one can be set
up the same way.

## What a round looks like to the listener

The listener gets a web page (a private claude.ai Artifact, shared from its Share menu) with
about 11 or 12 numbered pairs. Each pair has three players and three buttons:

- **Original, A and B.** A and B are the same 8 to 10 seconds of speech through two
  versions of the codec, or two transmissions. The original is included because some source
  recordings are band-limited or processed, and the question is which clip is closer to the
  source, not which sounds more "studio" (Jeff's request after round 4).
- **"A is better", "B is better", "No significant difference".** Tapping a chosen button
  again clears it.

Details that matter:

- The versions are hidden, and which one is A changes from pair to pair (a seeded shuffle).
  A and B are matched in loudness to the original, so the louder clip doesn't win by default.
- One pair is a **null pair**, two identical clips. If a listener picks a side on it, their
  close calls in that round are weak evidence.
- Only one player plays at a time. **Tapping or dragging on a progress bar starts playback
  from that point** (added in round 9), so you can jump to a word and hear it without also
  hitting play.
- Answers are kept in the browser's local storage, so a half-finished round survives a
  reload.
- At the bottom, the page builds an answer string, for example
  `sotto-ab-9 1:A 2:= 3:B ... | pair 5: B sounds hoarse`, with a copy button. The listener
  pastes it back into the project thread. Notes after `|` are optional and often the most
  useful part.
- Audio is 16-bit WAV at 8 kHz, because Artifacts don't serve FLAC. The repository keeps
  audio as FLAC.

## Building a round

1. **Choose the comparison and plan the pairs.**
   - Mix voices: female and male, LibriSpeech, EARS studio and VE9QRP.
   - Use voices held out from codebook training (`/mnt/project-files/vocoder/samples-clean/`)
     when the codebook is under test.
   - For radio channels, both sides of a pair go through the same simulated fades (same seed).
   - Add one null pair.
2. **Write a render script.** `tools/listening/render_ab9.py` is the current example. It
   writes `t{n}o.wav`, `t{n}a.wav` and `t{n}b.wav` for each pair, plus `key.json`. The key
   holds `trials` (the pair labels shown on the page) and `key` (what A and B really are, and
   the frame loss on channel pairs). Older rounds' scripts are in
   `/mnt/project-files/vocoder/listening/`. Run from the repository root:
   `python tools/listening/render_ab9.py OUT/audio`.
3. **Build the page.**
   `python tools/listening/build_page.py 9 "TITLE" intro.html OUT/key.json OUT/index.html`
   - The template is `tools/listening/ab_page.html`.
   - `intro.html` holds one to three short paragraphs: what the pairs are, what to listen
     for, and the voice sources and licences.
   - Don't hint which version is new.
4. **Publish** `OUT/index.html` as an Artifact, with the 3 × N WAV files passed as
   `audio/...` supporting files. Copy `key.json` to
   `/mnt/project-files/vocoder/listening/ab-N-key.json`.

## Reading the answers

Decode the answer string against `ab-N-key.json`. For each comparison, report wins, ties and
losses, check the null pair, and read the notes against the clips. Record the round, its link
and the result in the listening memory (`sotto-listening`), and record decisions in
`docs/encoder-v1.md`.

Rounds so far: 1 to 4 compared Codec 2 with sotto v1 to v3; 5 and 6 tested voiced fricatives
and mixed voicing; 7 and 8 tested concealment on fading 2 m. Round 9 tests depth-2
interleaving and the 29 KB codebook.

## Licences

- LibriSpeech is CC BY 4.0, and Speech Commands is CC BY 4.0.
- VE9QRP comes from the Codec 2 project.
- EARS is CC BY-NC 4.0. It may be used in private test pages, but EARS-derived audio or
  training data must not go into this MIT repository.
