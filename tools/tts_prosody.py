#!/usr/bin/env python3
"""Train sotto-tts's duration and pitch models on Kokoro speech.

    python tools/tts_prosody.py corpus --models KOKORO_DIR --out prosody_corpus.pkl
    python tools/tts_prosody.py train prosody_corpus.pkl [--out tts/data/prosody.bin]

`corpus`: Kokoro (af_heart) reads natural sentences: the Gospel of John and the first 600
verses of Acts (World English Bible, public domain; Luke is kept out for testing), given
the phones tts.frontend makes for them, so its timings line up with the synthesiser's own
phone sequences. Per phone it keeps the start and end time; per 20 ms the sotto 1200
analysis's pitch and voicing.

`train`: fits two small regression trees and writes them in the format tts/prosody.py reads:
  - duration: log phone duration from the phone's identity and class, stress, its place in
    the syllable, word and phrase, its neighbours, and the phrase type;
  - pitch: three log-pitch targets per vowel (20%, 50% and 80% of the way through it, as
    a ratio to the voice's median) from the syllable's stress, word type, place in the
    phrase and the phrase type, on the analysis's pitch track with its subharmonic errors
    fixed (clean_f0).
plus each punctuation mark's median pause. (The unit corpus from tools/tts_corpus.py is
mostly word lists, read with list intonation, so the models learn from sentences instead.)
SPDX-License-Identifier: MIT
"""
import argparse, json, os, pickle, sys, time, urllib.request
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]
from tts import frontend  # noqa: E402

WEB = "https://raw.githubusercontent.com/TehShrike/world-english-bible/master/json/{}.json"


def verses(book, limit=None):
    data = json.load(urllib.request.urlopen(WEB.format(book)))
    vs = {}
    for e in data:
        if "value" in e and "verseNumber" in e:
            vs.setdefault((e["chapterNumber"], e["verseNumber"]), []).append(e["value"])
    out = [" ".join(v).strip() for _, v in sorted(vs.items())]
    return out[:limit] if limit else out


def make_corpus(a):
    import tts_corpus, sotto_lr
    from scipy.signal import resample_poly
    from multiprocessing import Pool
    texts = verses("john") + verses("acts", 600)
    kok = tts_corpus.Kokoro(a.models, a.voice)
    recs, audio = [], []
    t0 = time.time()
    for i, s in enumerate(texts):
        phrases = frontend.text_to_phrases(s)
        utt = []
        for ph in phrases:
            for k, w in enumerate(ph["words"]):
                utt.append((w["phones"], ph["end"] if k == len(ph["words"]) - 1 else ""))
        if not utt or sum(len(p) for p, _ in utt) > 400:
            continue
        y, segs = kok.say(utt)
        audio.append(tts_corpus.level(resample_poly(y, 1, 3)).astype(np.float32))
        recs.append(dict(text=s, phrases=phrases, segs=segs))
        if i % 100 == 0:
            print(f"  {i}/{len(texts)} {time.time() - t0:.0f} s", flush=True)
    with Pool(os.cpu_count()) as pool:
        P = pool.map(_pitch, audio)
    for r, (wi, code) in zip(recs, P):
        r["wi"], r["code"] = wi, code
    pickle.dump(recs, open(a.out, "wb"))
    print(f"{len(recs)} utterances, {sum(len(x) for x in audio) / 8000 / 60:.1f} min")


def _pitch(x):
    import sotto_lr
    p = sotto_lr.Sotto1200().params(x)
    return p["wi"].astype(np.int16), p["code"].astype(np.int8)


def f0_hz(wi):
    import sotto_lr
    lr = sotto_lr.Sotto1200()
    return np.array([lr.wo_value(int(w)) for w in wi]) * 8000 / (2 * np.pi)


def clean_f0(f, voiced, med):
    """The sotto analysis's pitch track with its octave and third errors fixed: a voiced frame
    below 0.62 x the voice's median (5-10% of frames here, mostly at phrase ends) is taken
    as a subharmonic and multiplied by 2 or 3, whichever lands nearer the median of the
    trusted frames around it (+-0.3 s)."""
    f = f.copy()
    ok = voiced & (f > 0.62 * med) & (f < 2.2 * med)
    idx = np.flatnonzero(ok)
    for j in np.flatnonzero(voiced & ~ok):
        if f[j] >= 2.2 * med:
            f[j] = f[j] / 2
            continue
        near = idx[np.abs(idx - j) <= 15]
        ref = np.median(f[near]) if len(near) else med
        c = np.array([2 * f[j], 3 * f[j]])
        f[j] = c[np.argmin(np.abs(np.log(c / ref)))]
    return f


def plan_from(rec):
    """The synthesiser's own phone plan for the record's text, with Kokoro's timings."""
    from tts import prosody
    seq = prosody.phone_sequence(rec["phrases"])
    kp = [s for s in rec["segs"] if s[0] != "PAU"]
    sp = [q for q in seq if q["p"] != "PAU"]
    if len(kp) != len(sp):
        return None
    for q, k in zip(sp, kp):
        q["t0"], q["t1"] = float(k[3]), float(k[4])
    # pauses: Kokoro's own, between the phones around them
    for i, q in enumerate(seq):
        if q["p"] == "PAU":
            prev = seq[i - 1]["t1"] if i > 0 else 0.0
            nxt = next((r["t0"] for r in seq[i + 1:] if r["p"] != "PAU"), prev)
            q["t0"], q["t1"] = prev, max(prev, nxt)
    return seq


def train(a):
    from sklearn.tree import DecisionTreeRegressor
    from tts import prosody
    recs = pickle.load(open(a.corpus, "rb"))
    Xd, yd, Xp, yp, pauses = [], [], [], [], {}
    allf0 = []
    for r in recs:
        f = f0_hz(r["wi"])
        allf0.append(f[r["code"] > 0])
    med = float(np.median(np.concatenate(allf0)))
    skipped = 0
    for r in recs:
        seq = plan_from(r)
        if seq is None:
            skipped += 1
            continue
        feats = prosody.features(seq)
        voiced = r["code"] > 0
        f = clean_f0(f0_hz(r["wi"]), voiced, med)
        for q, ft in zip(seq, feats):
            if q["p"] == "PAU":
                if q.get("end") and q["t1"] > q["t0"]:
                    pauses.setdefault(q["end"], []).append(q["t1"] - q["t0"])
                continue
            d = q["t1"] - q["t0"]
            if d <= 0:
                continue
            Xd.append(ft["dur"])
            yd.append(np.log(d))
            if ft["pitch"] is not None:
                tg = []
                for x in (0.2, 0.5, 0.8):
                    t = q["t0"] + x * d
                    k = int(round((t + 0.012) / 0.02))       # frame centre at f*0.02-0.012
                    lo, hi = max(0, k - 2), min(len(f), k + 3)
                    v = [f[j] for j in range(lo, hi) if voiced[j]]
                    tg.append(np.log(np.median(v) / med) if v else np.nan)
                if not np.any(np.isnan(tg)):
                    Xp.append(ft["pitch"])
                    yp.append(tg)
    Xd, yd, Xp, yp = map(np.array, (Xd, yd, Xp, yp))
    print(f"{len(recs)} utterances ({skipped} skipped): {len(yd)} phones, {len(yp)} vowels; "
          f"median pitch {med:.0f} Hz")
    rng = np.random.default_rng(0)
    res = {}
    for name, X, y, leaves in (("dur", Xd, yd, a.dur_leaves), ("pitch", Xp, yp, a.pitch_leaves)):
        idx = rng.permutation(len(X))
        nt = len(X) // 10
        te, tr = idx[:nt], idx[nt:]
        m = DecisionTreeRegressor(max_leaf_nodes=leaves, min_samples_leaf=20, random_state=0)
        m.fit(X[tr], y[tr])
        e = np.sqrt(((m.predict(X[te]) - y[te]) ** 2).mean())
        e0 = np.sqrt(((y[tr].mean(0) - y[te]) ** 2).mean())
        print(f"{name}: {leaves} leaves, held-out rms {e:.3f} (log) against {e0:.3f} for the mean")
        m.fit(X, y)
        res[name] = m
    pause = {k: float(np.median(v)) for k, v in pauses.items() if len(v) > 5}
    print("pauses", {k: round(v, 3) for k, v in pause.items()})
    raw = prosody.write_model(res["dur"], res["pitch"], med, pause)
    open(a.out, "wb").write(raw)
    print(f"{a.out}: {len(raw)} bytes")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("corpus")
    c.add_argument("--models", required=True)
    c.add_argument("--voice", default="af_heart")
    c.add_argument("--out", required=True)
    t = sub.add_parser("train")
    t.add_argument("corpus")
    t.add_argument("--out", default=os.path.join(ROOT, "tts", "data", "prosody.bin"))
    t.add_argument("--dur-leaves", type=int, default=256)
    t.add_argument("--pitch-leaves", type=int, default=128)
    a = ap.parse_args()
    make_corpus(a) if a.cmd == "corpus" else train(a)


if __name__ == "__main__":
    main()
