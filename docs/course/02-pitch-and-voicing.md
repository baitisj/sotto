---
title: "2. Pitch and voicing"
---

# 2. Pitch and voicing

Previous: [Sound and bits](01-sound-and-bits.md) · [Course home](README.md) · Next: [The spectral envelope](03-envelope.md)

## Big idea

Your vocal cords open and close many times a second, like a very fast buzzer. How fast they buzz is your **pitch**. When they aren't buzzing (as in "s", "f" or a whisper), the sound is **unvoiced** hiss. sotto measures both every 10 milliseconds.

## A quick review: sine waves and frequency

A **sine wave** is the smoothest possible wiggle. It has:

- a **frequency**: how many times it repeats per second, measured in hertz (Hz),
- an **amplitude**: how big it is,
- a **phase**: where in its cycle it starts.

A 100 Hz sine wave repeats every 1/100 of a second = 10 ms. In general:

> period (seconds) = 1 / frequency (Hz)

## Pitch is the repeat rate

Look back at the zoomed vowel in chapter 1. The pattern repeated every 10.5 ms. So the man's pitch at that moment was:

> 1 / 0.0105 s ≈ **95 Hz**

Typical speaking pitches are roughly 85–155 Hz for adult men and 165–255 Hz for adult women. Your pitch also moves all the time: it rises at the end of a question and falls at the end of a sentence.

## A buzz is made of harmonics

Here is the surprising part, and it is the most important idea in sotto. **Any sound that repeats can be built by adding up sine waves whose frequencies are whole-number multiples of the repeat rate.** These sine waves are called **harmonics**. (This is a famous result in math called *Fourier analysis*.)

So a 95 Hz buzz is really 95 Hz + 190 Hz + 285 Hz + 380 Hz + ... all playing at once, each with its own loudness.

![The spectrum of one vowel, showing harmonics](figures/harmonics.svg)

This graph is a **spectrum**: instead of time along the bottom, it has *frequency*. Each peak is one harmonic. They sit exactly 95 Hz apart, all the way up to 4,000 Hz: 41 harmonics in all.

In the code, the number of harmonics is called **L**, and their loudnesses are called **A** (for amplitude). So the vowel in this picture is "L = 41 harmonics with amplitudes A₁, A₂, ... A₄₁".

## Pitch tracking

A **pitch tracker** (or pitch estimator) is the part of the encoder that measures the pitch. sotto v0 borrows Codec 2's tracker, called **NLP** ("non-linear pitch"). Roughly, it:

1. squares the signal, which makes the buzz rate stand out even when the lowest harmonic is weak (as it is on a phone line),
2. looks for the strongest repeating rate between 50 and 400 Hz,
3. checks nearby candidates and fine-tunes the answer.

![Spectrograms and pitch tracks for a man and a woman](figures/pitch.svg)

The top two pictures are **spectrograms**: time goes across, frequency goes up, and darker means louder. You can see the harmonics as thin parallel stripes. They're closer together for the man (low pitch) and further apart for the woman (higher pitch). When the stripes bend, the pitch is changing.

The bottom graph is what the pitch tracker reported. For the man it is smooth, around 95 Hz. For the woman it **jumps**: sometimes to about 350 Hz, sometimes down near 60 Hz. Her real pitch doesn't do that. These are **pitch errors**, often *octave errors*, where the tracker locks onto double or half the true pitch. A wrong pitch puts the harmonics in the wrong places, and it is one reason sotto currently sounds worse on women's voices. Better pitch tracking is on sotto's to-do list.

## Voicing

Not every sound is a buzz. To decide, Codec 2's **voicing detector** asks: *if I pretend this frame is a perfect set of harmonics at the measured pitch, how well does that match the real spectrum below 1,000 Hz?*

- A good match means a buzz: **voiced**.
- A bad match means noise: **unvoiced**.

It then double-checks with a simple rule: buzzes have most of their energy at low frequencies, and hiss has most of it at high frequencies.

sotto sends one voicing decision (1 bit: yes or no) for each 10 ms half of a frame, so 2 bits per 20 ms frame.

Real speech isn't always one or the other. A "z" or a "v" is a buzz *and* a hiss at the same time. A single yes/no can't describe that. Some vocoders (called MBE and MELP) send a separate voicing decision for different frequency bands. That's another idea on sotto's to-do list.

## How pitch is written in the code

The code doesn't store pitch in hertz. It uses **Wo** ("omega-zero"), the pitch written as an angle per sample:

> Wo = 2π × pitch ÷ 8000

So 95 Hz is Wo ≈ 0.075 radians per sample. The number of harmonics is L = ⌊π ÷ Wo⌋, which is the same as ⌊4000 ÷ pitch⌋. Chapter 4 shows how Wo is squeezed into 7 bits.

## Try it

1. A woman's pitch is 200 Hz. What is the period in milliseconds? How many harmonics fit below 4,000 Hz?
2. A tracker makes an octave error and reports 400 Hz instead of 200 Hz. Which of the true harmonics would the decoder be missing?
3. Whisper a sentence, then say it out loud. Which parts of the voice did you switch off when whispering?

## Where this is in the code

- `codec/codec2/src/nlp.c`: the NLP pitch tracker.
- `codec/codec2/src/sine.c`: `est_voicing_mbe()`, the voicing detector.
- `sim/vocoder_lab.py`: `analyse()` runs Codec 2's analysis (`c2sim --modelout`) and returns one record per 10 ms with `Wo`, `L`, `A`, `phi` and `voiced`.

<details markdown="1"><summary>Answers</summary>

1. 1/200 s = 5 ms. 4,000 ÷ 200 = 20 harmonics, the last one right at 4,000 Hz.
2. Every odd one: 200, 600, 1,000, 1,400 Hz and so on. Only the even ones (400, 800, ...) would be rebuilt, and the voice would sound an octave too high.
3. Whispering switches off voicing: every frame becomes unvoiced. You can hear this in chapter 5's "whisper" demo.

</details>
