"""Training shapes and held-out test clips from read-speech corpora.

Usage:
  python tools/clean_corpus.py librispeech LIBRISPEECH_DIR OUT.npz TEST_DIR [--test 8] [--seconds 240]
  python tools/clean_corpus.py ears EARS_DIR OUT.npz TEST_DIR [--test 8] [--seconds 120]

librispeech: the extracted LibriSpeech tree (SPEAKERS.TXT, dev-clean/<spk>/<chapter>/*.flac),
  CC BY 4.0. Download dev-clean from https://www.openslr.org/12.
ears: one folder per speaker (pXXX/*.flac at 8 kHz) holding the EARS "regular" read
  sentences, rainbow passages and freeform speech, CC BY-NC 4.0
  (https://github.com/facebookresearch/ears_dataset). Non-commercial: don't ship anything
  trained on it in this MIT repository.

`--test` speakers (half female, half male, chosen by a fixed seed) are held out. Each
gets one 12 s test clip of natural, untrimmed speech in TEST_DIR. The other speakers give
up to `--seconds` of speech each, analysed with sotto v3.3's tracker; the mean-removed
rate-K shapes of the non-silent 20 ms frames are saved in the same format as
tools/sc_corpus.py.
"""
import argparse, glob, json, os, sys
from multiprocessing import Pool
import numpy as np, soundfile as sf
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))
import vocoder_lab as vl                                       # noqa: E402


def to8k(x, fs):
    if x.ndim > 1:
        x = x.mean(1)
    return x if fs == 8000 else resample_poly(x, 8000, fs)


def librispeech(d):
    """-> {speaker: (sex, [files])}"""
    out = {}
    for line in open(os.path.join(d, "SPEAKERS.TXT"), encoding="utf-8"):
        if line.startswith(";"):
            continue
        f = [c.strip() for c in line.split("|")]
        if len(f) < 3:
            continue
        files = sorted(glob.glob(os.path.join(d, f[2], f[0], "*", "*.flac")))
        if files:
            out[f[0]] = (f[1], files)
    return out


def ears(d):
    st = json.load(open(os.path.join(d, "speaker_statistics.json")))
    out = {}
    for s in sorted(os.listdir(d)):
        files = sorted(glob.glob(os.path.join(d, s, "*.flac")))
        g = st.get(s, {}).get("gender", "")
        if files:
            out[s] = ({"female": "F", "male": "M"}.get(g, "?"), files)
    return out


def test_clip(files, kind, seconds=12.0):
    """One stretch of untrimmed speech: a long LibriSpeech utterance, or the start of an
    EARS rainbow passage (the first 0.5 s skipped)."""
    if kind == "ears":
        f = next((f for f in files if "rainbow_01" in f), files[0])
        x, fs = sf.read(f)
        x = to8k(x, fs)[4000:]
    else:
        lens = [sf.info(f).duration for f in files]
        f = next((f for f, n in zip(files, lens) if n >= seconds), files[int(np.argmax(lens))])
        x, fs = sf.read(f)
        x = to8k(x, fs)
    x = x[:int(seconds * 8000)]
    return 0.5 * x / np.abs(x).max()


def shapes(args):
    files, seconds = args
    parts, n = [], 0
    for f in files:
        x, fs = sf.read(f)
        x = to8k(x, fs)
        parts.append(x)
        n += len(x)
        if n > seconds * 8000:
            break
    x = np.concatenate(parts)[:int(seconds * 8000)]
    x = 0.5 * x / np.abs(x).max()
    m = vl.analyse(x, "tracked3")
    v = m["voiced"] > 0
    f0 = float(np.median(m["Wo"][v]) * vl.FS / (2 * np.pi)) if v.sum() > 20 else 0.0
    rk = vl.to_rate_k(m)[::2]
    mean = rk.mean(1)
    live = mean > np.percentile(mean, 25)
    return f0, (rk - mean[:, None])[live].astype(np.float32)


def main(kind, d, out, test_dir, n_test, seconds):
    spk = librispeech(d) if kind == "librispeech" else ears(d)
    rng = np.random.default_rng(1)
    test = []
    for sex in "FM":
        ss = sorted(s for s in spk if spk[s][0] == sex)
        test += list(rng.choice(ss, n_test // 2, replace=False))
    os.makedirs(test_dir, exist_ok=True)
    for s in test:
        sf.write(os.path.join(test_dir, f"{kind}_{s}_{spk[s][0].lower()}.flac"),
                 test_clip(spk[s][1], kind), 8000, subtype="PCM_16")
    train = [s for s in sorted(spk) if s not in test]
    print(f"{len(spk)} speakers: {len(test)} held out, {len(train)} for training", flush=True)
    # spread each speaker's files so read sentences, passages and freeform all appear
    with Pool(4) as p:
        res = p.map(shapes, [(list(rng.permutation(spk[s][1])), seconds) for s in train])
    sh = np.concatenate([r[1] for r in res])
    np.savez_compressed(out, shapes=sh,
                        speaker=np.concatenate([np.full(len(r[1]), i) for i, r in enumerate(res)]),
                        names=train, f0=[r[0] for r in res], held_out=test)
    print(sh.shape, "frames saved to", out, flush=True)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("kind", choices=["librispeech", "ears"])
    a.add_argument("dir")
    a.add_argument("out")
    a.add_argument("test_dir")
    a.add_argument("--test", type=int, default=8)
    a.add_argument("--seconds", type=float, default=240.0)
    a = a.parse_args()
    main(a.kind, a.dir, a.out, a.test_dir, a.test, a.seconds)
