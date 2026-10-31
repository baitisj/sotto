---
title: "How sotto works: a course"
permalink: /course/
---

# How sotto works: a course

**sotto** is an open-source *vocoder*: a program that turns your voice into a tiny stream of numbers, small enough to send over a radio, and then turns those numbers back into a voice at the other end. This course explains every piece of it, one chapter at a time.

It is written for a high-school student (about 10th grade). You need:

- a little algebra (graphs, powers of 2),
- the idea of a sine wave (we review it),
- curiosity about how your phone or a ham radio can squeeze a voice into almost nothing.

Every picture in the course is drawn from real recordings and from the real sotto code. Nothing is a cartoon.

![The whole system on one page](figures/pipeline.svg)

## Chapters

1. [Sound, numbers and the 2,400-bit budget](01-sound-and-bits.md): what a vocoder is and why we need one.
2. [Pitch and voicing](02-pitch-and-voicing.md): the buzz of your vocal cords, and the hiss of an "s".
3. [The spectral envelope](03-envelope.md): the shape of your mouth, and sotto's 20-point mel envelope.
4. [Quantization: fitting it into 48 bits](04-quantization.md): rounding, steps, and the vector quantizer for the shape.
5. [Synthesis: rebuilding the voice](05-synthesis.md): adding up sine waves, mixed voicing, and seven listening demos.
6. [Across the radio](06-radio.md): C4FM, error-correcting codes, fading, spreading and hiding lost frames.
7. [How we measure "better"](07-measuring.md): PESQ, oracles, the quantization ladder and listening tests.
8. [Glossary](glossary.md): every term used in the code and the design notes, in plain words.

Each chapter ends with **Try it** questions. Answers to the number questions are at the bottom of each chapter.

## A note on what's real

sotto is a research project and it is changing quickly. This course describes **sotto v3.5** (October 2026), as described in [`docs/encoder-v0.md`](../encoder-v0.md) and [`docs/encoder-v1.md`](../encoder-v1.md) (which covers v1 through v3.5). sotto is a Python prototype built on [Codec 2](https://github.com/drowe67/codec2), an older open-source vocoder, and borrows its analysis and synthesizer. sotto's own parts are a pitch and voicing tracker (chapter 2), mixed voicing (chapters 2 and 5), the 20-point envelope and its trained vector quantizer (chapters 3 and 4), and concealment of lost frames (chapter 6). It has been tested in simulation and by ear in a radio club's listening rounds, not yet on the air.

## Rebuilding the figures

```sh
./tools/build_codec2.sh            # builds c2sim, c2enc, c2dec
python tools/course_figures.py     # rewrites docs/course/figures/*.svg and docs/course/audio/*.flac
```

The script reads the clips in `docs/samples/` and the results in `docs/results/`.
