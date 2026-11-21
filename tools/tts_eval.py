#!/usr/bin/env python3
"""Score sotto-tts by machine listening: render sentences, transcribe them with the Parakeet
TDT 0.6B v2 speech recogniser (sherpa-onnx, int8), and report word error rate (WER).

    python tools/tts_eval.py --asr DIR [--tables tts/data/robot.stt tts/data/diphone.stt]
        [--ref-models KOKORO_DIR] [--out OUTDIR]

Systems: each table given, and with --ref-models the Kokoro voice the tables were cut from,
speaking the same phones, both plain (8 kHz) and through sotto 1200: the ceiling for a
table built from that voice. Sentences: Harvard sentences lists 1-3 (IEEE 1969, public
domain), 30 everyday sentences written for this test, and a few radio phrases (callsigns and
numbers are compared in spoken form).
SPDX-License-Identifier: MIT
"""
import argparse, json, os, re, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

HARVARD = """The birch canoe slid on the smooth planks.
Glue the sheet to the dark blue background.
It's easy to tell the depth of a well.
These days a chicken leg is a rare dish.
Rice is often served in round bowls.
The juice of lemons makes fine punch.
The box was thrown beside the parked truck.
The hogs were fed chopped corn and garbage.
Four hours of steady work faced us.
A large size in stockings is hard to sell.
The boy was there when the sun rose.
A rod is used to catch pink salmon.
The source of the huge river is the clear spring.
Kick the ball straight and follow through.
Help the woman get back to her feet.
A pot of tea helps to pass the evening.
Smoky fires lack flame and heat.
The soft cushion broke the man's fall.
The salt breeze came across from the sea.
The girl at the booth sold fifty bonds.
The small pup gnawed a hole in the sock.
The fish twisted and turned on the bent hook.
Press the pants and sew a button on the vest.
The swan dive was far short of perfect.
The beauty of the view stunned the young boy.
Two blue fish swam in the tank.
Her purse was full of useless trash.
The colt reared and threw the tall rider.
It snowed, rained, and hailed the same morning.
Read verse out loud for pleasure.""".splitlines()

EVERYDAY = """The farmer planted corn along the river.
My sister bought a new pair of boots.
We heard a loud noise from the kitchen.
The teacher wrote the answer on the board.
A small plane landed on the grassy field.
He forgot his keys at the office.
The dog chased the ball across the yard.
Please close the window before you leave.
The store sells fresh fish every Friday.
They painted the fence a bright shade of green.
The baby slept through the whole night.
I left my umbrella on the bus.
The mountain road was steep and narrow.
She sang a song about the ocean.
The doctor asked him to take a deep breath.
We need more paper for the printer.
The clock on the wall stopped at noon.
A gentle rain fell on the roof.
The workers built a wall of red brick.
He poured milk into a tall glass.
The candle burned down to a stub.
Our team won the game by two points.
The library closes early on Sunday.
A fox crept quietly past the barn.
The kettle whistled on the stove.
She wrapped the gift in silver paper.
The wind knocked over the trash can.
Turn off the lights when you go to bed.
The bakery smells of warm cinnamon.
He fixed the leak under the sink.""".splitlines()

RADIO = ["This is AG7EW.",
         "Is the repeater on the air tonight?",
         "The frequency is 440.850 megahertz.",
         "Battery low. Please charge the radio.",
         "Message received from AG7EW at nine thirty."]


def norm(s):
    """Spoken-form lower case words: callsigns and numbers (as the text or the recogniser
    writes them) expanded the way tts.frontend speaks them."""
    from tts import frontend
    s = s.replace("'s", "s").replace("-", " ")
    s = re.sub(r"(?i)\balpha\b", "alfa", s)
    s = re.sub(r"[^A-Za-z0-9./ ]", " ", s)
    out = []
    for t in s.split():
        t = t.strip("./")
        m = re.fullmatch(r"([0-9]{1,2})[.:]([0-9]{2})", t)
        if m:                                   # a time the recogniser wrote as 9.30
            out += frontend.cardinal(int(m.group(1))) + frontend.cardinal(int(m.group(2)))
            continue
        if t:
            out += [w for w, _ in frontend.expand(t)]
    return [w.lower() for w in out]


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    D = np.arange(len(h) + 1)
    for i, x in enumerate(r, 1):
        prev = D.copy()
        D[0] = i
        for j, y in enumerate(h, 1):
            D[j] = min(prev[j] + 1, D[j - 1] + 1, prev[j - 1] + (x != y))
    return int(D[-1]), len(r)


class ASR:
    def __init__(self, d):
        import sherpa_onnx
        j = lambda f: os.path.join(d, f)
        self.r = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=j("encoder.int8.onnx"), decoder=j("decoder.int8.onnx"),
            joiner=j("joiner.int8.onnx"), tokens=j("tokens.txt"),
            model_type="nemo_transducer", num_threads=os.cpu_count())

    def __call__(self, x, fs):
        from scipy.signal import resample_poly
        y = resample_poly(np.asarray(x, float), 16000, fs).astype(np.float32)
        s = self.r.create_stream()
        s.accept_waveform(16000, y)
        self.r.decode_stream(s)
        return s.result.text


def kokoro_say(kok, text):
    """Kokoro speaking the phones tts.frontend gives for text, at 8 kHz."""
    from tts import frontend
    from scipy.signal import resample_poly
    import tts_corpus
    utt = []
    for ph in frontend.text_to_phrases(text):
        words = ph["words"]
        for k, w in enumerate(words):
            utt.append((w["phones"], ph["end"] if k == len(words) - 1 else ""))
    y, _ = kok.say(utt)
    return tts_corpus.level(resample_poly(y, 1, 3))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asr", required=True)
    ap.add_argument("--tables", nargs="*", default=[os.path.join(ROOT, "tts", "data", f)
                                                   for f in ("robot.stt", "diphone.stt")])
    ap.add_argument("--ref-models")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--out")
    ap.add_argument("--json")
    ap.add_argument("--prosody", nargs="*", default=["rules"], choices=["trees", "rules"],
                    help="score each table with the trained trees, the rules, or both")
    a = ap.parse_args()
    import soundfile as sf
    from tts import synth
    asr = ASR(a.asr)
    systems = {}
    for t in a.tables:
        tab = synth.load_table(t)
        name = os.path.splitext(os.path.basename(t))[0]
        for pr in a.prosody:
            model = synth.load_prosody() if pr == "trees" else None
            if pr == "trees" and model is None:
                continue

            def run(text, tab=tab, model=model):
                p, rep = synth.synth_params(text, tab, model=model)
                return synth.decode_c(synth.encode(p)) / 32768.0
            systems[name + ("" if len(a.prosody) == 1 else "_" + pr)] = run
    if a.ref_models:
        import tts_corpus, sotto_lr
        kok = tts_corpus.Kokoro(a.ref_models, a.voice)
        lr = sotto_lr.Sotto1200()
        systems["kokoro"] = lambda text: kokoro_say(kok, text)
        systems["kokoro_sotto1200"] = lambda text: synth.decode_c(lr.encode(kokoro_say(kok, text))) / 32768.0
    res = {}
    for name, run in systems.items():
        for setname, S in (("harvard", HARVARD), ("everyday", EVERYDAY), ("radio", RADIO)):
            e = n = 0
            rows = []
            for k, s in enumerate(S):
                x = run(s)
                hyp = asr(x, 8000)
                ek, nk = wer(s, hyp)
                e, n = e + ek, n + nk
                rows.append((s, hyp, ek))
                if a.out:
                    os.makedirs(a.out, exist_ok=True)
                    sf.write(os.path.join(a.out, f"{name}_{setname}{k:02d}.wav"), x, 8000, subtype="PCM_16")
            res[f"{name}/{setname}"] = dict(wer=e / n, rows=rows)
            print(f"{name:18s} {setname:8s} WER {100 * e / n:5.1f}%  ({e}/{n})", flush=True)
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
