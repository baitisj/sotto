#!/usr/bin/env python3
"""Render sotto-tts demo phrases: one WAV and one .sot (sotto 1200 superframes) per phrase
and table, plus one WAV per table with all phrases in a row.

    python tools/tts_demo.py OUTDIR [--tables tts/data/robot.stt tts/data/diphone.stt]
        [--ref-models KOKORO_DIR]   # also the source voice, plain and through sotto 1200

SPDX-License-Identifier: MIT
"""
import argparse, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]

PHRASES = [
    ("callsign", "This is AG7EW."),
    ("fox", "The quick brown fox jumps over the lazy dog."),
    ("frequency", "The frequency is 440.850 megahertz."),
    ("question", "Is the repeater on the air tonight?"),
    ("battery", "Battery low. Please charge the radio."),
    ("anytext", "Sotto can say any text, even words it has never heard before."),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--tables", nargs="*", default=[os.path.join(ROOT, "tts", "data", f)
                                                   for f in ("robot.stt", "diphone.stt")])
    ap.add_argument("--ref-models")
    a = ap.parse_args()
    import soundfile as sf
    from tts import synth
    os.makedirs(a.out, exist_ok=True)
    gap = np.zeros(int(0.7 * 8000))
    systems = []
    for t in a.tables:
        tab = synth.load_table(t)
        systems.append((os.path.splitext(os.path.basename(t))[0], tab))
    rows = []
    for name, tab in systems:
        reel = []
        for key, text in PHRASES:
            p, rep = synth.synth_params(text, tab)
            bits = synth.encode(p)
            x = synth.decode_c(bits) / 32768.0
            sf.write(os.path.join(a.out, f"{name}_{key}.wav"), x, 8000, subtype="PCM_16")
            np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(
                os.path.join(a.out, f"{name}_{key}.sot"))
            reel += [x, gap]
            rows.append((name, key, rep["seconds"], 6 * len(bits), rep["phones"]))
        sf.write(os.path.join(a.out, f"{name}_all.wav"), np.concatenate(reel), 8000, subtype="PCM_16")
    if a.ref_models:
        import tts_corpus, tts_eval, sotto_lr
        kok = tts_corpus.Kokoro(a.ref_models, "af_heart")
        lr = sotto_lr.Sotto1200()
        for name in ("kokoro", "kokoro_sotto1200"):
            reel = []
            for key, text in PHRASES:
                x = tts_eval.kokoro_say(kok, text)
                if name != "kokoro":
                    x = synth.decode_c(lr.encode(x)) / 32768.0
                sf.write(os.path.join(a.out, f"{name}_{key}.wav"), x, 8000, subtype="PCM_16")
                reel += [x, gap]
            sf.write(os.path.join(a.out, f"{name}_all.wav"), np.concatenate(reel), 8000, subtype="PCM_16")
    for r in rows:
        print(f"{r[0]:10s} {r[1]:10s} {r[2]:5.2f} s {r[3]:5d} bytes  {r[4]}")


if __name__ == "__main__":
    main()
