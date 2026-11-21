#!/usr/bin/env python3
"""Cut sotto-tts's two unit tables from the aligned corpus (tools/tts_corpus.py).

    python tools/tts_build.py CORPUS.npz [--outdir tts/data] [--diphone-bits 34]

Writes robot.stt (the robotic phoneme table: 3 target frames per phone, each averaged over
every instance of the phone) and diphone.stt (for every phone pair in the corpus, the frames
from the middle of the first phone to the middle of the second, with the instances chosen
jointly so that the pairs that meet at each phone join well), and prints their sizes. Both share the duration table (median phone durations, stressed and not) and
the voice's median pitch.
SPDX-License-Identifier: MIT
"""
import argparse, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sim"))
from tts import phones as P, table as T  # noqa: E402

FRAME_T0 = -0.012       # time (s) of frame 0's centre: the analysis runs 12 ms ahead
                        # (measured: fricative/vowel contrast peaks there)


def load(path):
    import vocoder_lab as vl
    z = np.load(path)
    U = []
    for i in range(int(z["n"])):
        sh = z[f"u{i}_shape"].astype(float)
        U.append(dict(ph=[P.PHONES[k] for k in z[f"u{i}_ph"]], st=z[f"u{i}_st"],
                      wd=z[f"u{i}_wd"], t=z[f"u{i}_t"], code=z[f"u{i}_code"].astype(int),
                      wi=z[f"u{i}_wi"].astype(int), ei=z[f"u{i}_ei"].astype(int),
                      en=z[f"u{i}_en"].astype(float), c=(sh @ vl.DCT.T)[:, 1:]))
        if f"u{i}_rk10" in z.files:                 # the 10 ms analysis track
            rk = z[f"u{i}_rk10"].astype(float)
            U[-1]["c10"] = ((rk - rk.mean(1, keepdims=True)) @ vl.DCT.T)[:, 1:]
            U[-1]["en10"] = z[f"u{i}_en10"].astype(float)
            trim_pauses(U[-1])
    return U


def trim_pauses(d, drop=20.0):
    """Kokoro gives the silence next to a pause to the phone beside it (a phrase-final
    phone can run 200 ms into the silence). Move a phone's edge that touches a pause to
    where its energy comes within `drop` dB of the phone's peak."""
    t, ph, en = d["t"].astype(float).copy(), d["ph"], d["en10"]
    k10 = lambda x: int(np.clip(round((x - FRAME_T0) / 0.01), 0, len(en) - 1))
    for k, p in enumerate(ph):
        if p == "PAU":
            continue
        a, b = k10(t[k][0]), k10(t[k][1])
        if b - a < 2:
            continue
        seg = en[a:b + 1]
        on = np.where(seg > seg.max() - drop)[0]
        if k + 1 < len(ph) and ph[k + 1] == "PAU":
            nb = FRAME_T0 + 0.01 * (a + on[-1]) + 0.01
            nb = max(nb, t[k][0] + 0.03)
            if nb < t[k][1]:
                t[k][1] = nb
                t[k + 1][0] = nb
        if k > 0 and ph[k - 1] == "PAU":
            na = FRAME_T0 + 0.01 * (a + on[0]) - 0.005
            na = min(na, t[k][1] - 0.03)
            if na > t[k][0]:
                t[k][0] = na
                t[k - 1][1] = na
    d["t"] = t


def sample(d, t):
    """Shape (DCT 1..19), energy code and voicing code of utterance d at time t (s), from
    the 10 ms track (linear between its frames); voicing from the nearest 20 ms frame."""
    import sotto_lr
    x = np.clip((t - FRAME_T0) / 0.01, 0, len(d["c10"]) - 1)
    k = min(int(x), len(d["c10"]) - 2)
    w = x - k
    c = (1 - w) * d["c10"][k] + w * d["c10"][k + 1]
    en = (1 - w) * d["en10"][k] + w * d["en10"][k + 1]
    return c, sotto_lr.Sotto1200.e_index(en), int(d["code"][frame_at(d, ft(t))])


def ft(t):
    """Time (s) -> fractional frame position."""
    return (t - FRAME_T0) / 0.02


def instances(U):
    """{phone: [(utt, k, start frame pos, end frame pos, stress)]}"""
    inst = {}
    for u, d in enumerate(U):
        for k, p in enumerate(d["ph"]):
            a, b = ft(d["t"][k][0]), ft(d["t"][k][1])
            inst.setdefault(p, []).append((u, k, a, b, int(d["st"][k])))
    return inst


def frame_at(d, x):
    return int(np.clip(round(x), 0, len(d["c"]) - 1))


class Quant:
    def __init__(self):
        import sotto_lr
        self.vq = sotto_lr.Sotto1200().vq

    def search(self, c, shape_bits):
        q = self.vq
        if shape_bits == 18:
            import copy
            q = copy.copy(self.vq)
            q.cb = self.vq.cb[:2]
        return q._search(c)

    def sampled(self, d, ts, shape_bits):
        """Table frames sampled at times ts (s) of utterance d."""
        S = [sample(d, t) for t in ts]
        q = self.vq
        if shape_bits == 18:
            import copy
            q = copy.copy(self.vq)
            q.cb = self.vq.cb[:2]
        si = q._search(np.array([c for c, _, _ in S]))
        return [dict(code=v, ei=int(e), si=[int(x) for x in s]) for (c, e, v), s in zip(S, si)]

    def frames(self, d, idx, shape_bits):
        """Corpus frames idx of utterance d -> table frames (code, ei, stage indices)."""
        c = d["c"][idx]
        q = self.vq
        if shape_bits == 18:
            import copy
            q = copy.copy(self.vq)
            q.cb = self.vq.cb[:2]
        si = q._search(c)
        return [dict(code=int(d["code"][f]), ei=int(d["ei"][f]), si=[int(v) for v in s])
                for f, s in zip(idx, si)]


def durations(inst):
    dur = {}
    for p, L in inst.items():
        if p == "PAU":
            continue
        d1 = [(b - a) * 0.02 for _, _, a, b, s in L if s > 0]
        d0 = [(b - a) * 0.02 for _, _, a, b, s in L if s == 0]
        m0 = float(np.median(d0)) if d0 else None
        m1 = float(np.median(d1)) if d1 else None
        dur[p] = (m1 or m0, m0 or m1)
    dur["PAU"] = (0.25, 0.25)
    return dur


def centres(U, inst):
    """Each phone's average shape at its middle (DCT coefficients) and median energy."""
    cen = {}
    for p, L in inst.items():
        if p == "PAU":
            continue
        v = [U[u]["c"][frame_at(U[u], 0.5 * (a + b))] for u, _, a, b, _ in L]
        cen[p] = np.mean(v, 0)
    return cen


def robot_table(U, inst, Q, shape_bits=34):
    """3 targets per phone (start, middle, end), each the average over every instance of the
    phone (falls back to the single most typical instance when there is only one)."""
    units = {}
    for p, L in inst.items():
        if p == "PAU":
            continue
        n = 3       # 4 or 5 targets scored the same by machine listening
        traj, ok = [], []
        for u, k, a, b, s in L:
            if b - a < 1.5:
                continue
            pos = [a + (b - a) * (j + 0.5) / n for j in range(n)]
            traj.append(np.concatenate([U[u]["c"][frame_at(U[u], x)] for x in pos]))
            ok.append((u, pos))
        if not traj:
            u, k, a, b, s = L[0]
            ok = [(u, [0.5 * (a + b)] * n)]
            traj = [np.zeros(1)]
        traj = np.array(traj)
        med = traj.mean(0)
        best = int(np.argmin(((traj - med) ** 2).sum(1)))
        u, pos = ok[best]
        if len(ok) > 1:
            S = [[sample(U[uu], FRAME_T0 + 0.02 * x) for x in pp] for uu, pp in ok]
            fr = []
            for j in range(n):
                c = np.mean([s[j][0] for s in S], 0)
                e = int(np.median([s[j][1] for s in S]))
                v = int(np.bincount([s[j][2] for s in S]).argmax())
                fr.append((c, e, v))
            si = Q.search(np.array([f[0] for f in fr]), shape_bits)
            units[p] = [dict(code=v, ei=e, si=[int(x) for x in q]) for (c, e, v), q in zip(fr, si)]
        elif "c10" in U[u]:
            units[p] = Q.sampled(U[u], [FRAME_T0 + 0.02 * x for x in pos], shape_bits)
        else:
            units[p] = Q.frames(U[u], [frame_at(U[u], x) for x in pos], shape_bits)
    return units


def triphone_weights():
    """How often phone x comes before the pair a-b, and y after it: {(a, b): ({x: p},
    {y: p})}, from the 20,000 most frequent English words (CMUdict pronunciations,
    wordfreq frequencies), with pauses at word edges."""
    import cmudict, wordfreq
    d = cmudict.dict()
    left, right = {}, {}
    for w in wordfreq.top_n_list("en", 30000):
        if w not in d:
            continue
        f = wordfreq.word_frequency(w, "en")
        q = ["PAU"] + [P.from_arpabet(s)[0] for s in d[w][0]] + ["PAU"]
        for i in range(len(q) - 2):
            x, a, b = q[i], q[i + 1], q[i + 2]
            left.setdefault((a, b), {}).setdefault(x, 0.0)
            left[(a, b)][x] += f
            right.setdefault((x, a), {}).setdefault(b, 0.0)
            right[(x, a)][b] += f
    norm = lambda m: {k: v / sum(m.values()) for k, v in m.items()}
    return {k: norm(v) for k, v in left.items()}, {k: norm(v) for k, v in right.items()}


def diphone_table(U, inst, Q, cen, dur, shape_bits=34, iters=4, max_cand=40):
    """Per phone pair: frames from the middle of the first phone to the middle of the
    second, from one instance in the corpus. The instances are chosen together: each
    pair's pick minimises its duration mismatch plus the shape mismatch at both ends
    against the pairs it will meet there, weighted by how often English puts them side by
    side (so a coda L, as in "golf", is cut from an instance that matches the L of the
    L-F pair, not from an average L). Starts from the instances nearest each phone's
    average centre."""
    cand = {}
    for u, d in enumerate(U):
        ph = d["ph"]
        for k in range(len(ph) - 1):
            a, b = ph[k], ph[k + 1]
            if a == "PAU" and b == "PAU":
                continue
            sa, ea = ft(d["t"][k][0]), ft(d["t"][k][1])
            sb, eb = ft(d["t"][k + 1][0]), ft(d["t"][k + 1][1])
            if a == "PAU":                     # a pause gives its last (first) 80 ms
                sa = max(sa, ea - 4)
            if b == "PAU":
                eb = min(eb, sb + 4)
            m0, m1 = 0.5 * (sa + ea), 0.5 * (sb + eb)
            if m1 - m0 > 15:
                continue
            own = 0.0
            if a != "PAU":
                own += 4 * abs(np.log(max(ea - sa, 0.5) * 0.02 / dur[a][int(d["st"][k] == 0)]))
            if b != "PAU":
                own += 4 * abs(np.log(max(eb - sb, 0.5) * 0.02 / dur[b][int(d["st"][k + 1] == 0)]))
            t = lambda x: FRAME_T0 + 0.02 * x
            lv = sample(d, t(m0))[0] if a != "PAU" else None
            rv = sample(d, t(m1))[0] if b != "PAU" else None
            c0 = own + (np.sqrt(((lv - cen[a]) ** 2).sum()) if lv is not None else 0) + \
                (np.sqrt(((rv - cen[b]) ** 2).sum()) if rv is not None else 0)
            cand.setdefault((a, b), []).append(dict(u=u, m0=m0, mid=ea, m1=m1, own=own,
                                                    lv=lv, rv=rv, c0=c0))
    for k in cand:
        cand[k] = sorted(cand[k], key=lambda c: c["c0"])[:max_cand]
    pick = {k: 0 for k in cand}
    LW, RW = triphone_weights()
    dist = lambda x, y: np.sqrt(((x - y) ** 2).sum())
    for it in range(iters):
        changed = 0
        for (a, b), C in cand.items():
            lw = LW.get((a, b), {})           # x before a: the pair (x, a) meets us at a
            rw = RW.get((a, b), {})           # y after b: the pair (b, y) meets us at b
            best, bc = 0, None
            for i, c in enumerate(C):
                cost = c["own"]
                if c["lv"] is not None:
                    tot = 0.0
                    for x, w in lw.items():
                        if (x, a) in cand:
                            o = cand[(x, a)][pick[(x, a)]]
                            tot += w * dist(c["lv"], o["rv"])
                    cost += tot if lw else dist(c["lv"], cen[a])
                if c["rv"] is not None:
                    tot = 0.0
                    for y, w in rw.items():
                        if (b, y) in cand:
                            o = cand[(b, y)][pick[(b, y)]]
                            tot += w * dist(c["rv"], o["lv"])
                    cost += tot if rw else dist(c["rv"], cen[b])
                if bc is None or cost < bc:
                    best, bc = i, cost
            changed += best != pick[(a, b)]
            pick[(a, b)] = best
        print(f"  joint pick pass {it + 1}: {changed} changed", flush=True)
    units = {}
    for (a, b), C in cand.items():
        c = C[pick[(a, b)]]
        m0, mid, m1 = c["m0"], c["mid"], c["m1"]
        # frames at fixed places within each half (the half's length / 20 ms of them, a
        # pause's half as one silent frame), so that the synthesiser, which spreads them
        # the same way over its own halves, keeps every transition where it was
        t = lambda x: FRAME_T0 + 0.02 * x
        nl = 1 if a == "PAU" else max(1, int(round(mid - m0)))
        nr = 1 if b == "PAU" else max(1, int(round(m1 - mid)))
        while nl + nr > 15:
            nl, nr = (nl - 1, nr) if nl > nr else (nl, nr - 1)
        ts = [t(m0 + (mid - m0) * (j + 0.5) / nl) for j in range(nl)] + \
             [t(mid + (m1 - mid) * (j + 0.5) / nr) for j in range(nr)]
        fr = Q.sampled(U[c["u"]], ts, shape_bits)
        if a == "PAU":
            fr[0].update(ei=0, code=0)
        if b == "PAU":
            fr[-1].update(ei=0, code=0)
        units[(a, b)] = (nl, fr)
    return units


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "tts", "data"))
    ap.add_argument("--diphone-bits", type=int, default=34, choices=(18, 34))
    ap.add_argument("--robot-bits", type=int, default=18, choices=(18, 34))
    ap.add_argument("--suffix", default="")
    a = ap.parse_args()
    import sotto_lr
    lr = sotto_lr.Sotto1200()
    U = load(a.corpus)
    inst = instances(U)
    dur = durations(inst)
    wv = np.concatenate([d["wi"][d["code"] > 0] for d in U])
    f0 = float(np.median([lr.wo_value(int(w)) for w in wv])) * 8000 / (2 * np.pi)
    cen = centres(U, inst)
    Q = Quant()
    rob = robot_table(U, inst, Q, a.robot_bits)
    dip = diphone_table(U, inst, Q, cen, dur, a.diphone_bits)
    os.makedirs(a.outdir, exist_ok=True)
    rb = T.write("robot", a.robot_bits, f0, dur, rob)
    db = T.write("diphone", a.diphone_bits, f0, dur, dip)
    open(os.path.join(a.outdir, f"robot{a.suffix}.stt"), "wb").write(rb)
    open(os.path.join(a.outdir, f"diphone{a.suffix}.stt"), "wb").write(db)
    nfr = sum(len(f) for _, f in dip.values())
    print(f"voice f0 {f0:.0f} Hz")
    print(f"robot.stt   {len(rb):6d} bytes: {sum(len(v) for v in rob.values())} frames for {len(rob)} phones")
    print(f"diphone.stt {len(db):6d} bytes: {len(dip)} diphones, {nfr} frames "
          f"({nfr / len(dip):.1f} per diphone, {a.diphone_bits}-bit shapes)")


if __name__ == "__main__":
    main()
