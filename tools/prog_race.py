"""Score progressive sotto after each scan: PESQ-NB / ESTOI against the share of the clip's
bits received (docs/sotto-progressive.md).

Usage: python tools/prog_race.py [--samples DIR] [--modes 2400,1200,600,400] [--json OUT]
       python tools/prog_race.py --train-prior [--prior-samples DIR]
       python tools/prog_race.py --demo CLIP.flac --mode 2400 --script PI --out DIR

Default clips: the 16 held-out voices in /mnt/project-files/vocoder/samples-clean/. The prior
shapes (sim/data/prog_prior.npz) are trained on the six Codec 2 reference clips in
/mnt/project-files/vocoder/samples/ (none of them in the test set): the mean decoded v3.7
shape per voicing code over non-silent frames.
"""
import argparse, glob, json, os, sys
from multiprocessing import Pool
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
import audio_race as ar                                        # noqa: E402
import vocoder_lab as vl                                       # noqa: E402
import sotto_prog as sp                                        # noqa: E402

SAMPLES = "/mnt/project-files/vocoder/samples-clean"
PRIOR_SAMPLES = "/mnt/project-files/vocoder/samples"
CACHE = os.environ.get("PROG_CACHE", os.path.join(ROOT, "build", "prog-cache"))


def bits_for(mode, path, x):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f"{mode}__{os.path.splitext(os.path.basename(path))[0]}.npy")
    if os.path.exists(f):
        return np.load(f)
    b = sp.encode(mode, x)
    np.save(f, b)
    return b


def train_prior(samples):
    v = sp.codec("2400")
    acc = np.zeros((4, vl.K - 1))
    cnt = np.zeros(4)
    for path in sorted(glob.glob(os.path.join(samples, "*__original.wav"))):
        x, fs = sf.read(path)
        assert fs == 8000
        b = bits_for("2400", path, x)
        for row in b:
            f = sp.unpack("2400", row)
            if f["e"] == 0:
                continue
            acc[f["c"]] += sum(v.vq.cb[st][f[f"s{st}"]] for st in range(4))
            cnt[f["c"]] += 1
    prior = acc / np.maximum(cnt, 1)[:, None]
    np.savez(sp.PRIOR_PATH, prior=prior.astype(np.float32), count=cnt)
    print("prior frames per voicing code", cnt.astype(int).tolist(), "->", sp.PRIOR_PATH)


def job(args):
    mode, script, path = args
    x, fs = sf.read(path)
    assert fs == 8000
    b = bits_for(mode, path, x)
    scr = sp.SCRIPTS[mode][script]
    _, ends = sp.order(mode, len(b), scr)
    total = len(b) * 48
    rows = []
    for k in range(1, len(scr) + 1):
        kn = sp.known_after(mode, len(b), scr, k)
        y = sp.decode_audio(mode, b, kn)
        p, e = ar.score(x, y, ar.CODEC_DELAY)
        rows.append((k, ends[k - 1] / total, float(p), float(e)))
    return mode, script, os.path.basename(path), rows


def race(samples, modes, out):
    clips = sorted(glob.glob(os.path.join(samples, "*.flac")))
    jobs = [(m, s, p) for m in modes for s in sp.SCRIPTS[m] for p in clips]
    with Pool(4) as pool:
        r = pool.map(job, jobs)
    res = {}
    for mode, script, clip, rows in r:
        res.setdefault(f"{mode}/{script}", {})[clip] = rows
    summary = {}
    for key, per in res.items():
        mode, script = key.split("/")
        n = len(sp.SCRIPTS[mode][script])
        summary[key] = []
        for k in range(n):
            frac = list(per.values())[0][k][1]
            ps = [rows[k][2] for rows in per.values()]
            es = [rows[k][3] for rows in per.values()]
            fields = "+".join(",".join(f) + (f"/{st}:{ph}" if st > 1 else "")
                              for f, st, ph in [sp.SCRIPTS[mode][script][k]])
            summary[key].append(dict(scan=k + 1, fields=fields, share=round(frac, 3),
                                     pesq=round(float(np.mean(ps)), 3), estoi=round(float(np.mean(es)), 3)))
            print(f"{key:10s} scan {k + 1}  {frac * 100:5.1f}% of bits  PESQ {np.mean(ps):.3f}  "
                  f"ESTOI {np.mean(es):.3f}   after {fields}")
    if out:
        with open(out, "w") as f:
            json.dump(dict(clips=len(clips), summary=summary, per_clip=res), f, indent=1)


def streamed_good(ns, lost, depth=8, per=20, parity=False):
    """Good flags per superframe for today's XL slot interleave: packet k of group g carries
    slots g*F*D + s*D + k (F = 20 slots, D = depth); with parity, one XOR packet after each
    group gets back a group's single lost packet (blowfang docs/k6-pager.md)."""
    good = np.ones(ns, bool)
    G = per * depth
    k0 = 0
    for g0 in range(0, ns, G):
        nd = min(depth, -(-(ns - g0) // per))
        ok = [not lost(k0 + k) for k in range(nd)]
        k0 += nd
        if parity:
            pok = not lost(k0)
            k0 += 1
            if ok.count(False) == 1 and pok:
                ok = [True] * nd
        for k in range(nd):
            if not ok[k]:
                good[g0 + k:g0 + G:nd] = False
    return good


def loss_job(args):
    mode, script, path, cond = args
    x, fs = sf.read(path)
    b = bits_for(mode, path, x)
    ns = len(b)
    rng = np.random.default_rng(sum(map(ord, os.path.basename(path))))
    if cond.startswith("every"):
        n = int(cond[5:])
        draws = None
    else:
        rate = float(cond[4:])
        draws = rng.random(8192)

    def lost(k):
        return k % n == 3 if draws is None else draws[k] < rate
    out = {}
    v = sp.codec(mode)
    for par in (False, True):
        good = streamed_good(ns, lost, parity=par)
        out["streamed" + ("+par" if par else "")] = ar.score(x, vl.synthesise(v.decode(b, good)), ar.CODEC_DELAY)
    for name, block in (("prog-clip", None), ("prog-group", 160)):
        for par in ("none", "front"):
            rb, kn = sp.lost_packets(mode, b, sp.SCRIPTS[mode][script], block=block, lost=lost, parity=par)
            y = sp.decode_audio(mode, rb, kn)
            out[name + ("+par" if par != "none" else "")] = ar.score(x, y, ar.CODEC_DELAY)
    return mode, cond, os.path.basename(path), {k: (float(p), float(e)) for k, (p, e) in out.items()}


VARIANTS = ("streamed", "streamed+par", "prog-clip", "prog-clip+par", "prog-group", "prog-group+par")


def loss_race(samples, modes, conds, out):
    clips = sorted(glob.glob(os.path.join(samples, "*.flac")))
    jobs = [(m, LOSS_SCRIPT[m], p, c) for m in modes for c in conds for p in clips]
    with Pool(4) as pool:
        r = pool.map(loss_job, jobs)
    res = {}
    for mode, cond, clip, d in r:
        res.setdefault(f"{mode}/{cond}", {})[clip] = d
    summary = {}
    for key, per in res.items():
        summary[key] = {}
        for k in VARIANTS:
            p = np.mean([d[k][0] for d in per.values()])
            e = np.mean([d[k][1] for d in per.values()])
            summary[key][k] = dict(pesq=round(float(p), 3), estoi=round(float(e), 3))
        print(key, "  ".join(f"{k} {v['pesq']:.3f}/{v['estoi']:.3f}" for k, v in summary[key].items()))
    if out:
        with open(out, "w") as f:
            json.dump(dict(clips=len(clips), scripts=LOSS_SCRIPT, summary=summary, per_clip=res), f, indent=1)


LOSS_SCRIPT = {"2400": "SI", "1200": "SI", "600": "SI", "400": "SI"}


FPS = {"2400": 1, "1200": 2, "600": 4, "400": 6}     # 20 ms frames per superframe
# air time per second of speech, XL packets, 12-byte preambles (docs/sotto-progressive.md section 6)
LINKS = {("2400", "F1800"): 1.65, ("2400", "D2400"): 1.24, ("1200", "F1800"): 0.85, ("1200", "D2400"): 0.64}


def heard(mode, b, seq, ratio, t0, chunk_s=0.2):
    """What a receiver plays when it starts at t0 seconds into the transmission and plays each
    frame with whatever has arrived by the time it plays it. The link delivers the items of
    `seq` at a steady rate, the whole block in ratio x the clip's duration. Returns
    (frame params, received share at each chunk)."""
    ns = len(b)
    dur = 0.02 * FPS[mode]
    w = dict(sp.layout(mode))
    cum = np.cumsum([w[k] for _, k in seq])
    total = cum[-1]
    air = ratio * ns * dur
    per = max(1, int(round(chunk_s / dur)))
    fp, shares = [], []
    for s0 in range(0, ns, per):
        got = min(total, (t0 + s0 * dur) / air * total)
        k = int(np.searchsorted(cum, got, side="right"))
        f = sp.partial_frames(mode, b, sp.known_items(mode, ns, seq[:k]))
        fp += f[s0 * FPS[mode]:min(ns, s0 + per) * FPS[mode]]
        shares.append(got / total)
    return fp, shares


def heard_job(args):
    mode, link, path = args
    x, fs = sf.read(path)
    b = bits_for(mode, path, x)
    ns = len(b)
    r = LINKS[(mode, link)]
    scr = sp.SCRIPTS[mode]["SI"]
    _, ends = sp.order(mode, ns, scr)
    total = ns * 48
    first = ends[0] / total
    half = ends[2 if mode == "2400" else 1] / total
    clip_s = ns * 0.02 * FPS[mode]
    per = max(1, int(round(0.2 / (0.02 * FPS[mode]))))
    cases = {
        "progressive, start at scan 1": (sp.order(mode, ns, scr)[0], first),
        "just in time, start at scan 1": (sp.jit_order(mode, ns, scr, 1, r, lag=per), first),
        "progressive, start at half": (sp.order(mode, ns, scr)[0], half),
    }
    out = {}
    for name, (seq, share) in cases.items():
        t0 = share * r * clip_s
        fp, sh = heard(mode, b, seq, r, t0)
        y = vl.synthesise(sp.synth()._synth(fp))
        p, e = ar.score(x, y, ar.CODEC_DELAY)
        out[name] = dict(start_s=t0, start_frac=t0 / clip_s, pesq=float(p), estoi=float(e))
    # streamed: the earliest start that never runs dry is (ratio - 1) x the clip, full quality
    out["streamed"] = dict(start_s=max(0.0, r - 1) * clip_s, start_frac=max(0.0, r - 1))
    return mode, link, os.path.basename(path), out


def heard_race(samples, out):
    clips = sorted(glob.glob(os.path.join(samples, "*.flac")))
    jobs = [(m, l, p) for (m, l) in LINKS for p in clips]
    with Pool(4) as pool:
        r = pool.map(heard_job, jobs)
    res = {}
    for mode, link, clip, d in r:
        res.setdefault(f"{mode}/{link}", {})[clip] = d
    summary = {}
    for key, per in res.items():
        summary[key] = {}
        for name in list(per.values())[0]:
            rows = [d[name] for d in per.values()]
            sm = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in rows[0]}
            summary[key][name] = sm
            print(f"{key:12s} {name:32s} start {sm['start_frac'] * 12:5.1f} s of a 12 s clip"
                  + (f"  PESQ {sm['pesq']:.3f}  ESTOI {sm['estoi']:.3f}" if "pesq" in sm else "  full quality"))
    if out:
        with open(out, "w") as f:
            json.dump(dict(clips=len(clips), links=LINKS and {f"{m}/{l}": v for (m, l), v in LINKS.items()},
                           summary=summary, per_clip=res), f, indent=1)


def heard_demo(path, mode, link, out):
    """As heard by a receiver that starts playing once scan 1 is in: progressive order against
    the just-in-time order, on the given link."""
    os.makedirs(out, exist_ok=True)
    x, fs = sf.read(path)
    b = bits_for(mode, path, x)
    ns = len(b)
    r = LINKS[(mode, link)]
    scr = sp.SCRIPTS[mode]["SI"]
    _, ends = sp.order(mode, ns, scr)
    t0 = ends[0] / (ns * 48) * r * ns * 0.02 * FPS[mode]
    per = max(1, int(round(0.2 / (0.02 * FPS[mode]))))
    name = os.path.splitext(os.path.basename(path))[0]
    for tag, seq in (("progressive", sp.order(mode, ns, scr)[0]),
                     ("justintime", sp.jit_order(mode, ns, scr, 1, r, lag=per))):
        fp, _ = heard(mode, b, seq, r, t0)
        y = vl.synthesise(sp.synth()._synth(fp))
        sf.write(os.path.join(out, f"{name}__{mode}_{link}_asheard_{tag}_start{t0:.1f}s.wav"), y, 8000,
                 subtype="PCM_16")


def demo(path, mode, script, out):
    """One WAV per scan (what the receiver can play once that scan is in), plus a 'tour' WAV
    that plays them in order with a short gap."""
    os.makedirs(out, exist_ok=True)
    x, fs = sf.read(path)
    b = bits_for(mode, path, x)
    scr = sp.SCRIPTS[mode][script]
    _, ends = sp.order(mode, len(b), scr)
    name = os.path.splitext(os.path.basename(path))[0]
    tour = []
    for k in range(1, len(scr) + 1):
        y = sp.decode_audio(mode, b, sp.known_after(mode, len(b), scr, k))
        pct = round(100 * ends[k - 1] / (len(b) * 48))
        fn = os.path.join(out, f"{name}__{mode}{script}_scan{k}_{pct:03d}pct.wav")
        sf.write(fn, y, 8000, subtype="PCM_16")
        tour += [y, np.zeros(4000)]
    sf.write(os.path.join(out, f"{name}__{mode}{script}_tour.wav"), np.concatenate(tour), 8000, subtype="PCM_16")
    sf.write(os.path.join(out, f"{name}__original.wav"), x, 8000, subtype="PCM_16")
    # a weak station: 10% of packets lost, streamed with parity against progressive with
    # front parity (the same air time)
    rng = np.random.default_rng(sum(map(ord, os.path.basename(path))))
    draws = rng.random(8192)
    lost = lambda k: draws[k] < 0.1
    v = sp.codec(mode)
    y = vl.synthesise(v.decode(b, streamed_good(len(b), lost, parity=True)))
    sf.write(os.path.join(out, f"{name}__{mode}_loss10_streamed_parity.wav"), y, 8000, subtype="PCM_16")
    rb, kn = sp.lost_packets(mode, b, scr, lost=lost, parity="front")
    y = sp.decode_audio(mode, rb, kn)
    sf.write(os.path.join(out, f"{name}__{mode}{script}_loss10_progressive_parity.wav"), y, 8000, subtype="PCM_16")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=SAMPLES)
    ap.add_argument("--modes", default="2400,1200,600,400")
    ap.add_argument("--json")
    ap.add_argument("--train-prior", action="store_true")
    ap.add_argument("--prior-samples", default=PRIOR_SAMPLES)
    ap.add_argument("--loss", help="comma list: every8, rate0.1, ... (packet loss conditions)")
    ap.add_argument("--heard", action="store_true", help="playback while receiving")
    ap.add_argument("--demo")
    ap.add_argument("--mode", default="2400")
    ap.add_argument("--script", default="PI")
    ap.add_argument("--out", default="build/prog-demo")
    a = ap.parse_args()
    if a.train_prior:
        train_prior(a.prior_samples)
    elif a.heard and a.demo:
        for m, l in LINKS:
            heard_demo(a.demo, m, l, a.out)
    elif a.heard:
        heard_race(a.samples, a.json)
    elif a.loss:
        loss_race(a.samples, a.modes.split(","), a.loss.split(","), a.json)
    elif a.demo:
        demo(a.demo, a.mode, a.script, a.out)
    else:
        race(a.samples, a.modes.split(","), a.json)
