#!/usr/bin/env python3
"""Audition Kokoro's English voices for sotto-tts: each one reads the same lines, plain and
through sotto 1200, and Parakeet scores the sotto 1200 version.

    python tools/tts_voices.py --models KOKORO_DIR --asr PARAKEET_DIR --out DIR

Writes DIR/<voice>.wav (the voice says its name, the sample plain, then through sotto 1200),
DIR/all_plain.wav and DIR/all_sotto1200.wav (every voice in turn), and DIR/scores.json.
SPDX-License-Identifier: MIT
"""
import argparse, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]
from tts import frontend, synth  # noqa: E402

SAMPLE = "This is AG7EW on 440.850 MHz. The birch canoe slid on the smooth planks."
VOICES = ["af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole",
          "af_nova", "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric",
          "am_fenrir", "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice",
          "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis"]


def utterance(text):
    utt = []
    for ph in frontend.text_to_phrases(text):
        for k, w in enumerate(ph["words"]):
            utt.append((w["phones"], ph["end"] if k == len(ph["words"]) - 1 else ""))
    return utt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True)
    ap.add_argument("--asr")
    ap.add_argument("--out", required=True)
    ap.add_argument("--voices", nargs="*", default=VOICES)
    a = ap.parse_args()
    import soundfile as sf, sotto_lr, tts_corpus, tts_eval
    from scipy.signal import resample_poly
    os.makedirs(a.out, exist_ok=True)
    kok = tts_corpus.Kokoro(a.models, "af_heart")
    allv = np.load(os.path.join(a.models, "voices-v1.0.bin"))
    lr = sotto_lr.Sotto1200()
    asr = tts_eval.ASR(a.asr) if a.asr else None
    tests = tts_eval.RADIO + tts_eval.EVERYDAY[:10] + tts_eval.HARVARD[:10]
    say = lambda t: tts_corpus.level(resample_poly(kok.say(utterance(t))[0], 1, 3))
    s12 = lambda x: synth.decode_c(lr.encode(x)) / 32768.0
    gap = lambda s: np.zeros(int(s * 8000))
    scores, P, S = {}, [], []
    for v in a.voices:
        kok.voice = allv[v]
        name = say(f"{v[3:].capitalize()}.")
        x = say(SAMPLE)
        y = s12(x)
        sf.write(os.path.join(a.out, f"{v}.wav"), np.concatenate([name, gap(0.4), x, gap(0.7), y]),
                 8000, subtype="PCM_16")
        P += [name, gap(0.3), x, gap(0.8)]
        S += [s12(name), gap(0.3), y, gap(0.8)]
        if asr:
            e = n = 0
            for t in tests:
                ek, nk = tts_eval.wer(t, asr(s12(say(t)), 8000))
                e, n = e + ek, n + nk
            scores[v] = e / n
            print(f"{v:12s} WER through sotto 1200 {100 * e / n:5.1f}% ({e}/{n})", flush=True)
    sf.write(os.path.join(a.out, "all_plain.wav"), np.concatenate(P), 8000, subtype="PCM_16")
    sf.write(os.path.join(a.out, "all_sotto1200.wav"), np.concatenate(S), 8000, subtype="PCM_16")
    json.dump(scores, open(os.path.join(a.out, "scores.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
