#!/usr/bin/env python3
"""Build the phone-aligned speech corpus that sotto-tts cuts its units from.

The speech comes from the Kokoro v1.0 text-to-speech model (Apache-2.0, ONNX export from
github.com/thewh1teagle/kokoro-onnx releases), with one change: the model's own duration
predictor output is exposed as a second graph output, so every phoneme's start and end time
is known exactly, with no forced aligner. Pronunciations come from CMUdict (BSD licence),
and the texts are chosen so that every phone pair (diphone) the synthesiser can need occurs
at least a few times.

    python tools/tts_corpus.py --models DIR --out corpus.npz [--voice af_heart]

DIR holds kokoro-v1.0.onnx and voices-v1.0.bin (blowfang tools/tts_models.sh fetches them).
Needs numpy, scipy, onnx, onnxruntime, cmudict, and the sotto Python reference (sim/) for the
analysis. Writes per utterance: phones, stresses, word index, phone start/end (s), the per-20 ms
sotto 1200 analysis (voicing code, Wo index, energy code, energy dB, shape) and the 10 ms
rate-K envelopes and energies (tools/tts_build.py samples units from these).
SPDX-License-Identifier: MIT
"""
import argparse, json, os, random, sys, time
from multiprocessing import Pool
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sim"))
from tts import phones as P  # noqa: E402

FRAME = 0.02            # sotto analysis frame (s)
KOK_HOP = 600           # Kokoro: one duration unit = 600 samples at 24 kHz (25 ms)
KOK_FS = 24000
KOK_SHIFT = -1200       # Kokoro's audio runs this many samples ahead of its durations
                        # (measured on fricatives; tools/tts_corpus.py --calibrate)

# Plain sentences (written for this corpus) for natural phone durations and joins.
SENTENCES = """
The old boat drifted slowly toward the rocky shore.
She found a yellow kite caught high in the maple tree.
Please bring the heavy toolbox up from the garage.
A cold wind blew across the empty parking lot.
We watched the thunderstorm roll over the valley.
His brother fixed the bicycle chain with a small wrench.
The coffee shop opens at six every morning.
Fresh bread and butter make a fine breakfast.
My neighbor grows tomatoes, peppers and beans.
The children laughed at the clumsy puppy.
Turn left at the gas station and keep going north.
That museum has a huge collection of ancient coins.
Our train was delayed by a fallen branch.
The pilot checked the weather before takeoff.
Measure twice and cut once.
Rain is expected later this evening.
He wrote a long letter to his grandmother.
The bridge was closed for repairs all summer.
Could you pass the salt and pepper, please?
Every Thursday the market sells local honey.
The engine sputtered, coughed, and finally started.
Bright stars filled the clear desert sky.
Seven geese flew south over the frozen lake.
The judge listened carefully to both sides.
Jump into the pool and swim three lengths.
Thousands of people gathered in the square.
Leave the package by the back door.
The orange cat sleeps on the warm window ledge.
I think the battery needs a charge.
Measure the voltage across the red wire.
They usually eat dinner around seven thirty.
A quiet voice whispered from the hallway.
The garden hose has a leak near the faucet.
Watch out for ice on the bridge.
The radio crackled and then went silent.
Nobody knew where the treasure was buried.
Should we meet at noon or later?
The lighthouse beam swept across the water.
Push the green button to begin.
Please repeat the last number again.
""".strip().splitlines()


def load_cmudict():
    import cmudict
    return cmudict.dict()


def word_phones(d, w):
    """CMUdict's first pronunciation as [(phone, stress)], or None."""
    pr = d.get(w.lower())
    if not pr:
        return None
    return [P.from_arpabet(s) for s in pr[0]]


def tokenize(s):
    """Sentence -> list of (word, punct after)."""
    out = []
    for raw in s.split():
        w = raw.strip(",.?!;:")
        p = raw[len(raw.rstrip(",.?!;:")):] if raw[-1] in ",.?!;:" else ""
        out.append((w, p))
    return out


# ------------------------------------------------------------------ texts
def pairs_of(utt):
    """Diphones in an utterance: utt = list of words, each (phones[(p,s)], punct)."""
    seq = ["PAU"]
    for ph, punct in utt:
        seq += [p for p, _ in ph]
        if punct:
            seq.append("PAU")
    if seq[-1] != "PAU":
        seq.append("PAU")
    return list(zip(seq[:-1], seq[1:]))


def sentence_utt(d, s):
    u = []
    for w, p in tokenize(s):
        ph = word_phones(d, w.lower().strip("'"))
        if ph is None:
            return None
        u.append((ph, p))
    return u


def choose_texts(d, need=6, seed=1, pool=None):
    """Utterances (lists of (phones, punct)) covering every needed diphone `need` times:
    the plain sentences, then (with pool, a list of sentences) sentences picked greedily for
    the most uncovered pairs per phone, then CMUdict words picked greedily, then made-up
    carrier words."""
    rng = random.Random(seed)
    utts = []
    for s in SENTENCES:
        u = sentence_utt(d, s)
        if u is None:
            raise SystemExit(f"no CMUdict entry in: {s}")
        utts.append(u)
    words = [w for w in d if w.isalpha() and 3 <= len(w) <= 9]
    if pool:                     # sentence mode: only common words (no lists of rare names)
        import wordfreq
        words = [w for w in words if wordfreq.zipf_frequency(w, "en") >= 3.0]
    prons = {w: word_phones(d, w) for w in words}
    first = {p[0][0] for p in prons.values()}
    last = {p[-1][0] for p in prons.values()}
    target = set()
    for ph in prons.values():
        q = [p for p, _ in ph]
        target |= set(zip(q[:-1], q[1:]))
    target |= {(a, b) for a in last for b in first}
    target |= {("PAU", b) for b in first} | {(a, "PAU") for a in last}
    count = {}
    for u in utts:
        for pr in pairs_of(u):
            count[pr] = count.get(pr, 0) + 1
    if pool:
        import heapq
        cand = [u for u in (sentence_utt(d, s) for s in pool) if u]
        prs = [pairs_of(u) for u in cand]
        nph = [sum(len(ph) for ph, _ in u) for u in cand]

        def sgain(i):
            seen, g = {}, 0
            for pr in prs[i]:
                seen[pr] = seen.get(pr, 0) + 1
                if pr in target and count.get(pr, 0) + seen[pr] <= need:
                    g += 1
            return g / nph[i]
        heap = [(-sgain(i), rng.random(), i) for i in range(len(cand))]
        heapq.heapify(heap)
        picked = 0
        while heap:
            g0, r, i = heapq.heappop(heap)
            if -g0 < 0.02:                  # even the best bound: < 1 new pair in 50 phones
                break
            g = sgain(i)
            if g < 0.02:
                continue
            if heap and g < -heap[0][0]:
                heapq.heappush(heap, (-g, r, i))
                continue
            utts.append(cand[i])
            picked += 1
            for pr in prs[i]:
                count[pr] = count.get(pr, 0) + 1
        print(f"{picked} sentences from the pool of {len(cand)}")

    wp = {}
    for w in words:
        q = [p for p, _ in prons[w]]
        wp[w] = set(zip(q[:-1], q[1:]))

    def gain(w):
        return sum(1 for pr in wp[w] if count.get(pr, 0) < need)

    # lazy greedy word cover of the word-internal pairs (gains only shrink; shorter words
    # win ties)
    import heapq
    heap = [(-gain(w), len(w), rng.random(), w) for w in words]
    heap = [h for h in heap if h[0] < 0]
    heapq.heapify(heap)
    chosen = []
    while heap:
        g0, ln, r, w = heapq.heappop(heap)
        g = gain(w)
        if g == 0:
            continue
        if heap and -g > heap[0][0]:
            heapq.heappush(heap, (-g, ln, r, w))
            continue
        chosen.append(w)
        for pr in wp[w]:
            count[pr] = count.get(pr, 0) + 1
    rng.shuffle(chosen)
    for i in range(0, len(chosen), 8):
        grp = chosen[i:i + 8]
        u = [(prons[w], "," if j == 3 and len(grp) > 4 else "") for j, w in enumerate(grp)]
        u[-1] = (u[-1][0], ".")
        utts.append(u)
        for pr in pairs_of(u):
            count[pr] = count.get(pr, 0) + 1
    # carriers for whatever is still short (cross-word and pause pairs mostly)
    missing = [pr for pr in sorted(target) if count.get(pr, 0) < need]
    carriers = []
    for a, b in missing:
        for _ in range(need - count.get((a, b), 0)):
            carriers.append(carrier(a, b))
    rng.shuffle(carriers)
    for i in range(0, len(carriers), 6):
        u = [(w, p) for w, p in carriers[i:i + 6]]
        u[-1] = (u[-1][0], ".")
        utts.append(u)
    return utts, target, chosen


def _stress(seq):
    """Primary stress on the first full vowel of a made-up word."""
    out, done = [], False
    for p in seq:
        s = 0
        if P.is_vowel(p) and p not in ("AX", "AXR") and not done:
            s, done = 1, True
        out.append((p, s))
    return out


def carrier(a, b):
    """A made-up word holding the pair a-b; ('word phones', punct after)."""
    if a == "PAU":
        post = ["AA", "T"] if not P.is_vowel(b) else ["T"]
        return _stress([b] + post), ""          # follows the previous word's comma
    if b == "PAU":
        pre = ["T", "AA"] if not P.is_vowel(a) else ["T"]
        return _stress(pre + [a]), ","
    pre = ["T", "AA"] if not P.is_vowel(a) else ["T"]
    post = ["AA", "T"] if not P.is_vowel(b) else ["T"]
    return _stress(pre + [a, b] + post), ""


# ------------------------------------------------------------------ Kokoro
class Kokoro:
    def __init__(self, models, voice):
        import onnx, onnxruntime as ort
        src = os.path.join(models, "kokoro-v1.0.onnx")
        dur = os.path.join(models, "kokoro-v1.0-dur.onnx")
        if not os.path.exists(dur):
            m = onnx.load(src)
            m.graph.output.append(onnx.helper.make_tensor_value_info(
                "/encoder/Clip_output_0", onnx.TensorProto.FLOAT, None))
            onnx.save(m, dur)
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(os.environ.get("KOKORO_THREADS", "0"))
        self.sess = ort.InferenceSession(dur, so, providers=["CPUExecutionProvider"])
        self.voice = np.load(os.path.join(models, "voices-v1.0.bin"))[voice]
        import importlib.util     # the vocabulary ships in the kokoro-onnx package's config.json
        loc = importlib.util.find_spec("kokoro_onnx").submodule_search_locations[0]
        cfg = json.load(open(os.path.join(loc, "config.json")))
        self.vocab = cfg["vocab"]

    def say(self, utt, speed=1.0):
        """utt: list of (phones[(p, s)], punct). Returns 24 kHz audio and per phone
        (phone, stress, word index, start s, end s), pauses included as PAU."""
        chars, owner = [], []           # owner: ('p', k) phone k, ('s',) space, ('x',) punct
        plist = []
        for wi, (ph, punct) in enumerate(utt):
            if wi:
                chars.append(" ")
                owner.append(("s",))
            for p, s in ph:
                k = len(plist)
                plist.append((p, s, wi))
                if s:
                    chars.append("ˈ" if s == 1 else "ˌ")
                    owner.append(("p", k))
                for c in P.KOKORO[p]:
                    chars.append(c)
                    owner.append(("p", k))
            if punct:
                chars.append(punct)
                owner.append(("x",))
        tok = [0] + [self.vocab[c] for c in chars] + [0]
        owner = [("x",)] + owner + [("x",)]
        st = self.voice[min(len(chars), len(self.voice) - 1)].reshape(1, -1).astype(np.float32)
        audio, dur = self.sess.run(None, {"tokens": np.array([tok], np.int64), "style": st,
                                          "speed": np.array([speed], np.float32)})
        dur = dur.ravel().astype(int)
        t = np.concatenate([[0], np.cumsum(dur)]) * KOK_HOP + KOK_SHIFT    # samples
        t = t / KOK_FS
        # phone spans; a space's time is split between its neighbours
        span = {}
        for i, o in enumerate(owner):
            if o[0] == "p":
                a, b = span.get(o[1], (t[i], t[i + 1]))
                span[o[1]] = (min(a, t[i]), t[i + 1])
        for i, o in enumerate(owner):
            if o[0] == "s":
                mid = 0.5 * (t[i] + t[i + 1])
                kl = owner[i - 1][1] if owner[i - 1][0] == "p" else None
                kr = owner[i + 1][1] if owner[i + 1][0] == "p" else None
                if kl is not None:
                    span[kl] = (span[kl][0], mid)
                if kr is not None:
                    span[kr] = (mid, span[kr][1])
        segs, prev_end = [], 0.0
        for k, (p, s, wi) in enumerate(plist):
            a, b = span[k]
            if a - prev_end > 0.03:
                segs.append(("PAU", 0, -1, prev_end, a))
            segs.append((p, s, wi, a, b))
            prev_end = b
        end = len(audio.ravel()) / KOK_FS
        if end - prev_end > 0.0:
            segs.append(("PAU", 0, -1, prev_end, end))
        return audio.ravel(), segs


# ------------------------------------------------------------------ analysis
def level(x, target_db=-26.0):
    """Active-speech level to target_db (10 ms blocks within 30 dB of the loudest)."""
    b = x[: len(x) // 80 * 80].reshape(-1, 80)
    e = 10 * np.log10((b ** 2).mean(1) + 1e-12)
    act = e > e.max() - 30
    rms = np.sqrt((b[act] ** 2).mean())
    return x * (10 ** (target_db / 20) / rms)


def analyse(x8):
    """sotto 1200's analysis: per 20 ms frame (voicing code, Wo and energy codes, energy,
    mean-removed shape) and the 10 ms rate-K envelopes and energies behind them."""
    import sotto_lr, vocoder_lab as vl
    c = sotto_lr.Sotto1200()
    p = c.params(x8)
    m = vl.analyse(x8, c.PITCH)
    rk = vl.to_rate_k(m)
    en = vl.frame_energy_db(vl.from_rate_k(m, rk))
    return dict(code=p["code"].astype(np.int8), wi=p["wi"].astype(np.int16),
                ei=p["ei"].astype(np.int8), en=p["en"].astype(np.float32),
                shape=p["shape"].astype(np.float32), rk10=rk.astype(np.float32),
                en10=en.astype(np.float32))


def reanalyse(src, dst, jobs):
    """The corpus src with every utterance's analysis redone from its stored audio."""
    d = np.load(src, allow_pickle=True)
    out = {k: d[k] for k in d.files}
    n = int(d["n"])
    audio = [d[f"u{i}_pcm"].astype(np.float32) / 32767 for i in range(n)]
    t0 = time.time()
    with Pool(jobs) as pool:
        feats = pool.map(analyse, audio)
    for i, f in enumerate(feats):
        for k, v in f.items():
            out[f"u{i}_{k}"] = v
    np.savez_compressed(dst, **out)
    print(f"{dst}: {n} utterances re-analysed in {time.time() - t0:.0f} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models")
    ap.add_argument("--out", required=True)
    ap.add_argument("--reanalyse", metavar="IN.npz", help="only redo the sotto analysis of an "
                    "existing corpus's audio (after an encoder change); no Kokoro needed")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--need", type=int, default=6, help="instances wanted per diphone")
    ap.add_argument("--wav", help="also write the 8 kHz corpus audio here (one WAV)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--sentences", help="a file of sentences (one a line) to cover the pairs "
                    "with first, before word lists and carriers")
    ap.add_argument("--dry", action="store_true", help="only report the text choice")
    a = ap.parse_args()
    if a.reanalyse:
        return reanalyse(a.reanalyse, a.out, a.jobs)
    if not a.models:
        ap.error("--models is needed to make a corpus")
    from scipy.signal import resample_poly
    d = load_cmudict()
    pool = open(a.sentences).read().splitlines() if a.sentences else None
    utts, target, chosen = choose_texts(d, a.need, pool=pool)
    if a.dry:
        nw = sum(len(u) for u in utts)
        print(f"{len(utts)} utterances, {nw} words, {len(chosen)} cover words")
        return
    print(f"{len(utts)} utterances, {len(chosen)} cover words, {len(target)} target diphones")
    kok = Kokoro(a.models, a.voice)
    t0 = time.time()
    audio, segs = [], []
    for i, u in enumerate(utts):
        y, s = kok.say(u)
        x8 = level(resample_poly(y, 1, 3))
        audio.append(x8.astype(np.float32))
        segs.append(s)
        if i % 50 == 0:
            print(f"  {i}/{len(utts)} {time.time() - t0:.0f} s", flush=True)
    with Pool(a.jobs) as pool:
        feats = pool.map(analyse, audio)
    tot = sum(len(x) for x in audio) / 8000
    print(f"corpus {tot / 60:.1f} min, synth+analysis {time.time() - t0:.0f} s")
    out = dict(voice=a.voice, n=len(utts))
    for i, (x, s, f) in enumerate(zip(audio, segs, feats)):
        out[f"u{i}_pcm"] = np.round(np.clip(x, -1, 1) * 32767).astype(np.int16)
        out[f"u{i}_ph"] = np.array([P.ID[p] for p, *_ in s], np.int8)
        out[f"u{i}_st"] = np.array([q[1] for q in s], np.int8)
        out[f"u{i}_wd"] = np.array([q[2] for q in s], np.int16)
        out[f"u{i}_t"] = np.array([[q[3], q[4]] for q in s], np.float32)
        for k, v in f.items():
            out[f"u{i}_{k}"] = v
    np.savez_compressed(a.out, **out)
    if a.wav:
        import soundfile as sf
        sf.write(a.wav, np.concatenate(audio), 8000, subtype="PCM_16")


if __name__ == "__main__":
    main()
