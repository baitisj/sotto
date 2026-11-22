#!/usr/bin/env python3
"""Build the data for the diphone hunt page (docs/diphone-hunt.html): every diphone of a
sotto-tts table, heard three ways and scored.

    python tools/diphone_hunt.py --models KOKORO_DIR [--table tts/data/diphone.stt]
        [--voice af_sarah] [--out OUTDIR] [--jobs 4]

For each phone pair in the table, a common English word that contains it (CMUdict
pronunciation, wordfreq frequency; a pair that only happens across words gets a two-word
phrase, a pair with a pause gets a word that starts or ends with the phone) is:

  1. reference: said by Kokoro (the voice the table was cut from), 8 kHz;
  2. codec: the reference through sotto 1200 (the reference encoder, sim/sotto_lr.py, and
     the K6's fixed-point decoder);
  3. slim: the reference through the K6's slim encoder (c/fixed/sotto_slim_enc -a slim
     -c slim) and the same decoder;
  4. synth: said by sotto-tts from the table, same phones, rule prosody.

So 1 vs 2 (or 3) is what an encoder does to the diphone and 2 vs 4 is what the table does.
Every clip carries a fingerprint (the first 8 hex digits of the SHA-1 of its sotto bits, or
of the reference's samples), so two columns that are secretly the same render show up. Each
pair is scored over its own span (middle of the first phone to middle of the second):
codec damage = reference vs codec, table damage = synthesiser frames vs the reference
analysis, each the shape distance (dB RMS over the 19 DCT coefficients) plus energy steps
plus 2 per point (of 6) where voicing disagrees; pitch_gross counts reference frames where the
sotto analysis pitch is more than 1.4x off pYIN.

Writes OUTDIR/hunt.json (per pair: word, phones, the pair's span in each clip, scores,
where the table cut it from) and OUTDIR/{ref,codec,slim,synth}.wav (8 kHz G.711 mu-law, the clips
back to back; offsets in hunt.json).
SPDX-License-Identifier: MIT
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]
from tts import synth, frontend, phones as P  # noqa: E402

FS = 8000
GAP = int(0.15 * FS)       # silence between clips in the packed files
EDGE = 0.08                # s of pause taken as a pause's half


def cmu_phones(pron):
    return [P.from_arpabet(s) for s in pron]


def pick_items(pairs, top=30000):
    """{(a, b): (words [(text, phones)], how)} for every pair."""
    import cmudict, wordfreq
    d = cmudict.dict()
    words = []
    for w in wordfreq.top_n_list("en", top):
        if re.fullmatch(r"[a-z]{3,}|a|i|an|as|at|be|by|do|go|he|if|in|is|it|me|my|no|of|oh|on|or|so|to|up|us|we", w) \
                and w in d:
            ph = cmu_phones(d[w][0])
            if len(ph) <= 9:
                words.append((w, ph))
    inside, first, last = {}, {}, {}
    def plain(pron, i):  # an edge vowel CMUdict marks unstressed but full ("africa" ...K AA0)
        s = pron[i]
        return not (s[-1] == "0" and s[:-1] not in ("AH", "IH", "IY", "ER", "OW", "UW"))
    for w, ph in words:
        q = [p for p, _ in ph]
        if plain(d[w][0], 0):
            first.setdefault(q[0], (w, ph))
        if plain(d[w][0], -1):
            last.setdefault(q[-1], (w, ph))
        for a, b in zip(q, q[1:]):
            inside.setdefault((a, b), (w, ph))
    out = {}
    for a, b in pairs:
        if a == "PAU" and b in first:
            out[(a, b)] = ([first[b]], "word start")
        elif b == "PAU" and a in last:
            out[(a, b)] = ([last[a]], "word end")
        elif (a, b) in inside:
            out[(a, b)] = ([inside[(a, b)]], "inside a word")
        elif a in last and b in first:
            out[(a, b)] = ([last[a], first[b]], "across words")
    return out


def pair_span(segs, nwords_phones, a, b, how):
    """The pair's span (s) in a clip: Kokoro segs [(p, s, word, t0, t1)]."""
    ph = [s for s in segs if s[0] != "PAU"]
    mid = lambda s: 0.5 * (s[3] + s[4])
    if a == "PAU":
        return ph[0][3] - EDGE, mid(ph[0])
    if b == "PAU":
        return mid(ph[-1]), ph[-1][4] + EDGE
    if how == "across words":
        k = nwords_phones[0] - 1
        return mid(ph[k]), mid(ph[k + 1])
    for k in range(len(ph) - 1):
        if ph[k][0] == a and ph[k + 1][0] == b:
            return mid(ph[k]), mid(ph[k + 1])
    return None


def cvec(shape):
    import vocoder_lab as vl
    return (shape @ vl.DCT.T)[:, 1:]


def fp(b):
    return hashlib.sha1(np.ascontiguousarray(b).tobytes()).hexdigest()[:8]


def slim_bits(x):
    """The K6 slim encoder's bits (48 per superframe) for 8 kHz float audio."""
    exe = os.path.join(ROOT, "c", "fixed", "sotto_slim_enc")
    with tempfile.TemporaryDirectory() as d:
        np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tofile(f"{d}/in.raw")
        subprocess.run([exe, "-a", "slim", "-c", "slim", f"{d}/in.raw", f"{d}/out.bit"],
                       check=True, stdout=subprocess.DEVNULL)
        return np.unpackbits(np.fromfile(f"{d}/out.bit", np.uint8)).reshape(-1, 48)


def damage(ca, ea, va, cb, eb, vb):
    d = float(np.sqrt(((ca - cb) ** 2).mean(1)).mean())
    de = float(np.abs(ea.astype(int) - eb.astype(int)).mean())
    dv = int(((va > 0) != (vb > 0)).sum())
    return round(d, 2), round(de, 2), dv, round(d + de + 2 * dv, 2)


_W = {}


def worker_init(models, voice, table):
    import tts_corpus, sotto_lr
    _W["kok"] = tts_corpus.Kokoro(models, voice)
    _W["lr"] = sotto_lr.Sotto1200()
    _W["tab"] = synth.load_table(table)


def one(job):
    import tts_corpus, tts_build, librosa
    from scipy.signal import resample_poly
    (a, b), wl, how = job
    kok, lr, tab = _W["kok"], _W["lr"], _W["tab"]
    utt = [(ph, "" if i < len(wl) - 1 else ".") for i, (_, ph) in enumerate(wl)]
    y, segs = kok.say(utt)
    x = tts_corpus.level(resample_poly(y, 1, 3)).astype(np.float64)
    e = np.sqrt((x[: len(x) // 80 * 80].reshape(-1, 80) ** 2).mean(1))
    on = np.flatnonzero(e > e.max() * 10 ** (-40 / 20))
    i0, i1 = max(0, (on[0] - 3) * 80), min(len(x), (on[-1] + 4) * 80)
    span = pair_span(segs, [len(wl[0][1])], a, b, how)
    if span is None:
        return None
    x = x[i0:i1]
    sp = (span[0] - i0 / FS, span[1] - i0 / FS)
    # 2: through sotto 1200
    fit = lambda v: v[: len(x)] if len(v) >= len(x) else np.pad(v, (0, len(x) - len(v)))
    bc = np.asarray(lr.encode(x), np.uint8)
    yc = fit(synth.decode_c(bc) / 32768.0)
    bl = slim_bits(x)
    yl = fit(synth.decode_c(bl) / 32768.0)
    # 3: the synthesiser, same phones
    text = " ".join(w for w, _ in wl)
    fix = {w: ph for w, ph in wl}
    old = frontend.pronounce
    frontend.pronounce = lambda w: fix.get(w) or old(w)
    try:
        p, _ = synth.synth_params(text.capitalize() + ".", tab, words=None)
        seq, _ = synth.phone_plan(text.capitalize() + ".", tab)
    finally:
        frontend.pronounce = old
    bs = np.asarray(synth.encode(p), np.uint8)
    ys = synth.decode_c(bs) / 32768.0
    ss = [q for q in seq if q["p"] != "PAU"]
    smid = lambda q: 0.5 * (q["t0"] + q["t1"])
    if a == "PAU":
        s_sp = (ss[0]["t0"] - EDGE, smid(ss[0]))
    elif b == "PAU":
        s_sp = (smid(ss[-1]), ss[-1]["t1"] + EDGE)
    else:
        k = next((k for k in range(len(ss) - 1) if ss[k]["p"] == a and ss[k + 1]["p"] == b), None)
        if how == "across words":
            k = len(wl[0][1]) - 1
        if k is None:
            return None
        s_sp = (smid(ss[k]), smid(ss[k + 1]))
    e = np.sqrt((ys[: len(ys) // 80 * 80].reshape(-1, 80) ** 2).mean(1))
    on = np.flatnonzero(e > e.max() * 10 ** (-40 / 20))
    j0, j1 = max(0, (on[0] - 3) * 80), min(len(ys), (on[-1] + 4) * 80)
    ys = ys[j0:j1]
    s_sp_clip = (s_sp[0] - j0 / FS, s_sp[1] - j0 / FS)
    # scores over the pair's span, 6 points each
    T0 = tts_build.FRAME_T0
    qr, qc, ql = lr.params(x), lr.params(yc), lr.params(yl)
    fr = lambda q, t: np.clip(np.round((t - T0) / 0.02).astype(int), 0, len(q["ei"]) - 1)
    tr = np.linspace(sp[0], sp[1], 6)
    kr, kc = fr(qr, tr), fr(qc, tr)
    codec = damage(cvec(qr["shape"])[kr], qr["ei"][kr], qr["code"][kr],
                   cvec(qc["shape"])[kc], qc["ei"][kc], qc["code"][kc])
    kl = fr(ql, tr)
    slim = damage(cvec(qr["shape"])[kr], qr["ei"][kr], qr["code"][kr],
                  cvec(ql["shape"])[kl], ql["ei"][kl], ql["code"][kl])
    ts = np.linspace(s_sp[0], s_sp[1], 6)
    ks = np.clip(np.round(ts / 0.02).astype(int), 0, len(p["ei"]) - 1)
    table = damage(cvec(qr["shape"])[kr], qr["ei"][kr], qr["code"][kr],
                   cvec(p["shape"])[ks], p["ei"][ks], p["code"][ks])
    f0p, vp, _ = librosa.pyin(x.astype(np.float32), fmin=60, fmax=500, sr=FS, frame_length=512,
                              hop_length=160, center=True)
    kk = np.clip(np.round(tr / 0.02).astype(int), 0, len(f0p) - 1)
    gross = 0
    for j, k in zip(kr, kk):
        if qr["code"][j] and vp[k] and f0p[k] > 0:
            f = lr.wo_value(int(qr["wi"][j])) * FS / (2 * np.pi)
            gross += abs(np.log2(f / f0p[k])) > np.log2(1.4)
    return dict(pair=f"{a}-{b}", text=text, how=how,
                phones=" ".join(f"{p}{s or ''}" for _, ph in wl for p, s in ph),
                ref=x.astype(np.float32), codec=yc.astype(np.float32), slim=yl.astype(np.float32),
                synth=ys.astype(np.float32),
                fp=dict(ref=fp(np.round(x * 32767).astype("<i2")), codec=fp(bc), slim=fp(bl), synth=fp(bs)),
                slim_damage=slim[3], slim_parts=slim[:3],
                span=[round(v, 3) for v in sp], sspan=[round(v, 3) for v in s_sp_clip],
                codec_damage=codec[3], codec_parts=codec[:3], table_damage=table[3],
                table_parts=table[:3], pitch_gross=int(gross))


def g711(x):
    """float -1..1 -> G.711 mu-law bytes."""
    s = np.clip(np.round(np.asarray(x) * 32767), -32767, 32767).astype(np.int32)
    sign = np.where(s < 0, 0x80, 0)
    m = np.minimum(np.abs(s), 32635) + 0x84
    e = np.floor(np.log2(m)).astype(np.int32) - 7
    mant = (m >> (e + 3)) & 0x0F
    return (~(sign | (e << 4) | mant) & 0xFF).astype(np.uint8)


def ulaw_wav(x, path):
    """An ordinary 8 kHz G.711 mu-law WAV (format 7), so the packs play anywhere."""
    import struct
    b = g711(x).tobytes()
    fmt = struct.pack("<HHIIHHH", 7, 1, FS, FS, 1, 8, 0)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"fact" + struct.pack("<II", 4, len(b)) + b"data" + struct.pack("<I", len(b)) + b
            + (b"\0" if len(b) & 1 else b""))
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True)
    ap.add_argument("--table", default=os.path.join(ROOT, "tts", "data", "diphone.stt"))
    ap.add_argument("--voice", default="af_sarah")
    ap.add_argument("--sources", help="the table's --sources JSON from tools/tts_build.py")
    ap.add_argument("--out", default="hunt")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    from multiprocessing import Pool
    tab = synth.load_table(a.table)
    pairs = sorted(tab["units"])
    items = pick_items(pairs)
    jobs = [(k, *items[k]) for k in pairs if k in items][: a.limit]
    print(f"{len(pairs)} pairs, {len(jobs)} with words", flush=True)
    with Pool(a.jobs, worker_init, (a.models, a.voice, a.table)) as pool:
        res = []
        for i, r in enumerate(pool.imap(one, jobs, chunksize=4)):
            if r:
                res.append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    src = json.load(open(a.sources)) if a.sources else {}
    os.makedirs(a.out, exist_ok=True)
    meta, packs = [], {"ref": [], "codec": [], "slim": [], "synth": []}
    pos = {k: 0 for k in packs}
    for r in res:
        m = {k: v for k, v in r.items() if k not in packs}
        for k in packs:
            m[k] = [pos[k], len(r[k])]
            packs[k] += [r[k], np.zeros(GAP, np.float32)]
            pos[k] += len(r[k]) + GAP
        if r["pair"] in src:
            m["source"] = src[r["pair"]]
        meta.append(m)
    for k, v in packs.items():
        ulaw_wav(np.concatenate(v), os.path.join(a.out, f"{k}.wav"))
    json.dump(dict(fs=FS, table=os.path.basename(a.table), voice=a.voice, items=meta),
              open(os.path.join(a.out, "hunt.json"), "w"), separators=(",", ":"))
    print(f"{len(meta)} pairs -> {a.out}/hunt.json, " +
          ", ".join(f"{k}.wav {pos[k] / FS / 60:.1f} min" for k in packs))


if __name__ == "__main__":
    main()
