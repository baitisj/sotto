"""Progressive sotto: the same frames as the streamed (linear) modes, sent in scans.

A streamed sotto clip sends each 48-bit superframe whole, in time order. A progressive clip
sends the same bits for a block of superframes (a whole stored clip, or a block of a second
or two of live audio) in *scans*, like a progressive JPEG: first the voicing, pitch and
energy of every superframe in the block, then the shape stages, coarse ones first. After
the last scan the receiver holds exactly the streamed bitstream, so the full decode is the
existing decoder and stays bit-exact; before that, a partial decoder fills the missing fields.

    scan   one or more fields of the mode's layout, for every superframe of the block or for
           one phase of it (every 2nd superframe from 0, then from 1: time interlacing)
    script the ordered list of scans; it must cover every field of every superframe once

Partial decoding (`partial_frames`), per 20 ms frame:
    voicing / pitch / energy missing (interlaced scan not arrived): from the nearest frames
        that have them, as sotto 1200's B rule (pitch and energy halfway, voicing copied)
    shape stages missing: the sum of the stages that have arrived (each stage of the
        multistage codebook refines the ones before it)
    no shape stage at all: linear between the nearest frames that have one, else the prior
        shape for the frame's voicing code (PRIOR, 4 x 19 values, trained on clips that are
        not in the test set by tools/prog_race.py --train-prior)

Modes: "2400" (v3.7 frame per 20 ms), "1200", "600", "400" (their own layouts). The
partial decoder runs the v3.7 synthesis that every mode shares (sotto_lr.Sotto1200._synth).
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vocoder_lab as vl
import sotto_lr as lr
import sotto_vlr as vr

PRIOR_PATH = os.path.join(HERE, "data", "prog_prior.npz")

LAYOUT_2400 = [("c", 2), ("w", 7), ("e", 5), ("s0", 9), ("s1", 9), ("s2", 8), ("s3", 8)]

# Scan scripts: (fields, step, phase). step 1 = every superframe; step 2, phase 0/1 = the even
# then the odd superframes. Named by mode; "linear" is the streamed order (one scan per
# superframe is the same thing as all fields, step 1, in time order, so it is listed apart).
VPE = {"2400": ("c", "w", "e"), "1200": ("ca", "wa", "ea", "cb", "dw", "de"),
       "600": ("v", "wc", "ws", "em", "er"), "400": ("v", "wc", "ws", "em", "er")}

SCRIPTS = {
    "2400": {
        # P: pitch+energy, then each shape stage for all frames
        "P": [(("c", "w", "e"), 1, 0), (("s0",), 1, 0), (("s1",), 1, 0), (("s2", "s3"), 1, 0)],
        # PI: as P with the first two shape stages interlaced in time (even frames first)
        "PI": [(("c", "w", "e"), 1, 0), (("s0",), 2, 0), (("s0",), 2, 1),
               (("s1",), 2, 0), (("s1",), 2, 1), (("s2", "s3"), 1, 0)],
        # PII: the pitch and energy interlaced too (a 40 ms prosody sketch first)
        "PII": [(("c", "w", "e"), 2, 0), (("c", "w", "e"), 2, 1), (("s0",), 2, 0), (("s0",), 2, 1),
                (("s1",), 2, 0), (("s1",), 2, 1), (("s2", "s3"), 1, 0)],
        # SI (recommended): pitch, energy and the first shape stage of every other frame
        # first (a 40 ms sketch at 24% of the bits), then the odd frames, then the finer stages
        "SI": [(("c", "w", "e", "s0"), 2, 0), (("c", "w", "e"), 2, 1), (("s0",), 2, 1),
               (("s1",), 2, 0), (("s1",), 2, 1), (("s2",), 1, 0), (("s3",), 1, 0)],
    },
    "1200": {
        "P": [(("ca", "wa", "ea"), 1, 0), (("cb", "dw", "de"), 1, 0), (("sa0",), 1, 0),
              (("sa1",), 1, 0), (("sb",), 1, 0)],
        "PS": [(("ca", "wa", "ea"), 1, 0), (("sa0",), 1, 0), (("cb", "dw", "de"), 1, 0),
               (("sa1",), 1, 0), (("sb",), 1, 0)],
        "SI": [(("ca", "wa", "ea", "sa0"), 2, 0), (("ca", "wa", "ea", "sa0"), 2, 1),
               (("cb", "dw", "de"), 1, 0), (("sa1",), 1, 0), (("sb",), 1, 0)],
    },
    "600": {
        "P": [(("v", "wc", "ws", "em", "er"), 1, 0), (("a0s0", "a1s0"), 1, 0),
              (("a0s1", "a1s1"), 1, 0)],
        "PI": [(("v", "wc", "em"), 1, 0), (("ws", "er"), 1, 0), (("a0s0",), 1, 0),
               (("a1s0",), 1, 0), (("a0s1", "a1s1"), 1, 0)],
        "SI": [(("v", "wc", "em", "a0s0"), 1, 0), (("ws", "er", "a1s0"), 1, 0),
               (("a0s1", "a1s1"), 1, 0)],
    },
    "400": {
        "P": [(("v", "wc", "ws", "em", "er"), 1, 0), (("a0s0",), 1, 0), (("a1s0", "a2s0"), 1, 0)],
        "PI": [(("v", "wc", "em"), 1, 0), (("ws", "er"), 1, 0), (("a0s0",), 1, 0),
               (("a2s0",), 1, 0), (("a1s0",), 1, 0)],
        "SI": [(("v", "wc", "em", "a0s0"), 1, 0), (("ws", "er", "a2s0"), 1, 0), (("a1s0",), 1, 0)],
    },
}

_CODEC = {}


def codec(mode):
    """The mode's Python reference (cached): SottoV37 for 2400, else Sotto1200 / SottoVLR."""
    if mode not in _CODEC:
        _CODEC[mode] = {"2400": lambda: vl.SottoV37(), "1200": lambda: lr.Sotto1200(),
                        "600": lambda: vr.SottoVLR("600"), "400": lambda: vr.SottoVLR("400")}[mode]()
    return _CODEC[mode]


_SYN = None


def synth():
    """sotto 1200's per-20 ms synthesis (the v3.7 decoder core), shared by every mode."""
    global _SYN
    if _SYN is None:
        _SYN = codec("1200")
    return _SYN


def layout(mode):
    return LAYOUT_2400 if mode == "2400" else codec(mode).layout()


def offsets(mode):
    out, p = {}, 0
    for k, w in layout(mode):
        out[k] = (p, w)
        p += w
    return out


def check_script(mode, script):
    """Every field of every superframe exactly once."""
    names = [k for k, w in layout(mode) if w]
    for k in names:
        cover = [(st, ph) for fields, st, ph in script if k in fields]
        res = sorted(r for st, ph in cover for r in range(ph, 2, st)) if cover else []
        assert res == [0, 1] or (cover and all(st == 1 for st, _ in cover) and len(cover) == 1), (mode, k, cover)
    return True


def golden_step(n):
    """Q for spread_order: the integer nearest n / phi^2 (0.382 n) that shares no factor
    with n, so s -> s * Q mod n is a permutation."""
    if n <= 2:
        return 1
    q = max(1, int(round(n * 0.3819660112501051)))
    while np.gcd(q, n) != 1:
        q += 1
    return q


def spread_order(sel):
    """Order of the superframes `sel` (n of them, in time order) inside one scan: superframe
    j goes at position j * Q mod n, Q = golden_step(n). Neighbouring superframes are then
    about 0.38 n positions apart, so a lost run shorter than that (one lost packet) never
    takes two neighbours, and by the three-gap theorem the superframes it does take are
    spread evenly over the block. Position i carries superframe i * Q^-1 mod n; a receiver
    needs Q^-1 once per scan size (extended Euclid), then one multiply and a modulo per
    item, so a Cortex-M0 needs no table."""
    n = len(sel)
    qi = pow(golden_step(n), -1, n) if n > 1 else 0
    return [sel[(i * qi) % n] for i in range(n)]


def order(mode, ns, script):
    """Transmission order for a block of ns superframes: list of (superframe, field), and the
    cumulative bit count at the end of each scan."""
    check_script(mode, script)
    w = dict(layout(mode))
    seq, ends, n = [], [], 0
    for fields, step, phase in script:
        for s in spread_order(list(range(phase, ns, step))):
            for k in fields:
                if w[k]:
                    seq.append((s, k))
                    n += w[k]
        ends.append(n)
    return seq, ends


def permutation(mode, ns, script):
    """Bit permutation: position p of the progressive block carries streamed bit perm[p]
    (index into the ns*48 streamed bits)."""
    off = offsets(mode)
    bits = sum(w for _, w in layout(mode))
    perm = []
    for s, k in order(mode, ns, script)[0]:
        p, wd = off[k]
        perm += [s * bits + p + i for i in range(wd)]
    perm = np.array(perm)
    assert sorted(perm) == list(range(ns * bits))
    return perm


def to_progressive(mode, bits, script):
    b = np.asarray(bits).reshape(-1)
    return b[permutation(mode, len(bits), script)]


def from_progressive(mode, pbits, ns, script, got=None):
    """Back to streamed superframes, plus the per-(superframe, field) known mask. pbits may
    be a received prefix (shorter than ns*48), or the whole block with `got` marking which of
    its bits arrived (lost packets)."""
    perm = permutation(mode, ns, script)
    nb = sum(w for _, w in layout(mode))
    out = np.zeros(ns * nb, np.int8)
    have = np.zeros(ns * nb, bool)
    m = len(pbits)
    g = np.ones(m, bool) if got is None else np.asarray(got, bool)
    out[perm[:m][g]] = np.asarray(pbits)[g]
    have[perm[:m][g]] = True
    off = offsets(mode)
    known = {k: np.array([have[s * nb + p: s * nb + p + w].all() if w else True for s in range(ns)])
             for k, (p, w) in off.items()}
    return out.reshape(ns, nb), known


def lost_packets(mode, bits, script, block=None, packet_bits=960, lost=lambda k: False,
                 parity="none"):
    """Send `bits` progressively in blocks of `block` superframes (None: the whole clip),
    each block's bit stream cut into packets of packet_bits (an XL packet's 120 speech
    bytes); packets for which lost(k) is true (k counts every packet sent, parity included)
    are dropped. parity: "none"; "all8", one XOR parity packet per 8 data packets (the K6's
    section-14 parity); "front", one per 4 packets over the first half of each block's
    packets only (the same air time, spent on the scans that matter most). A parity group
    with one packet lost gets it back. Returns the received superframes and the known mask."""
    ns = len(bits)
    block = block or ns
    out, known, k0 = [], None, 0
    for s0 in range(0, ns, block):
        b = bits[s0:s0 + block]
        pb = to_progressive(mode, b, script)
        npk = -(-len(pb) // packet_bits)
        ok = np.array([not lost(k0 + k) for k in range(npk)])
        k0 += npk
        if parity == "all8":
            groups = [list(range(i, min(i + 8, npk))) for i in range(0, npk, 8)]
        elif parity == "front":
            nf = (npk + 1) // 2
            groups = [list(range(i, min(i + 4, nf))) for i in range(0, nf, 4)]
        else:
            groups = []
        for g in groups:
            pok = not lost(k0)
            k0 += 1
            miss = [k for k in g if not ok[k]]
            if len(miss) == 1 and pok:
                ok[miss[0]] = True
        got = np.repeat(ok, packet_bits)[:len(pb)]
        o, kn = from_progressive(mode, pb, len(b), script, got)
        out.append(o)
        known = kn if known is None else {f: np.concatenate([known[f], kn[f]]) for f in kn}
    return np.concatenate(out), known


def known_after(mode, ns, script, nscans):
    """Known mask after the first nscans scans (nscans = len(script): everything)."""
    known = {k: np.zeros(ns, bool) for k, _ in layout(mode)}
    for k, w in layout(mode):
        if not w:
            known[k][:] = True
    for fields, step, phase in script[:nscans]:
        for k in fields:
            known[k][phase::step] = True
    return known


def unpack(mode, b):
    off = offsets(mode)
    return {k: (int("".join(map(str, b[p:p + w])), 2) if w else 0) for k, (p, w) in off.items()}


# ---------------------------------------------------------------- prior shapes
def load_prior(path=PRIOR_PATH):
    if not os.path.exists(path):
        return np.zeros((4, vl.K - 1))
    return np.load(path)["prior"]


def _fill_time(vals, have):
    """Linear in time between the frames that have a value; held at the ends. vals: (n, d)."""
    idx = np.where(have)[0]
    out = np.array(vals, float)
    if len(idx) == 0:
        return out, False
    for d in range(out.shape[1]):
        out[:, d] = np.interp(np.arange(len(out)), idx, out[idx, d])
    return out, True


def _fill_vpe(code, wi, ei, have):
    """Voicing / pitch / energy for frames that lack them: from the neighbours with them,
    sotto 1200's B rule (halfway pitch when both voiced, the voiced one's otherwise, energy
    halfway, voicing of the earlier neighbour with an edge read as mixed)."""
    n = len(code)
    idx = np.where(have)[0]
    code, wi, ei = code.copy(), wi.copy(), ei.copy()
    if len(idx) == 0:
        return code * 0, wi, ei * 0
    for f in np.where(~have)[0]:
        a = idx[idx < f]
        b = idx[idx > f]
        a = a[-1] if len(a) else None
        b = b[0] if len(b) else None
        if a is None:
            a = b
        if b is None:
            b = a
        va, vb = code[a] != 0, code[b] != 0
        if va and vb:
            wi[f] = (wi[a] + wi[b] + 1) >> 1
        else:
            wi[f] = wi[a] if va or not vb else wi[b]
        ei[f] = (ei[a] + ei[b] + 1) >> 1
        c = code[a] if (f - a) <= (b - f) else code[b]
        code[f] = 2 if c == 3 else c
    return code, wi, ei


# ---------------------------------------------------------------- partial decoders
def partial_frames(mode, bits, known, prior=None):
    """Per 20 ms frame parameters (code, wi, ei, shape) from the superframes `bits` with only
    the fields marked in `known` (dict field -> bool per superframe) trusted."""
    prior = load_prior() if prior is None else prior
    if mode == "2400":
        return _partial_2400(bits, known, prior)
    if mode == "1200":
        return _partial_1200(bits, known, prior)
    return _partial_vlr(mode, bits, known, prior)


def _shape_out(code, c, have, prior):
    """Shape DCT coefs (n, K-1) with `have` marking frames that carry their own: the rest
    linear between them, or the voicing prior when no frame has one."""
    c, ok = _fill_time(c, have)
    if not ok:
        c = prior[np.asarray(code)]
    out = []
    for q in c:
        z = np.zeros(vl.K)
        z[1:] = q
        out.append(z @ vl.DCT)
    return out


def _partial_2400(bits, known, prior):
    vq = codec("2400").vq
    F = [unpack("2400", b) for b in np.asarray(bits)]
    n = len(F)
    hv = known["c"] & known["w"] & known["e"]
    code = np.array([f["c"] for f in F])
    wi = np.array([f["w"] for f in F])
    ei = np.array([f["e"] for f in F])
    code, wi, ei = _fill_vpe(code, wi, ei, hv)
    c = np.zeros((n, vl.K - 1))
    hs = known["s0"].copy()
    for f in range(n):
        for st in range(4):
            if known[f"s{st}"][f] and known["s0"][f]:
                c[f] += vq.cb[st][F[f][f"s{st}"]]
    sh = _shape_out(code, c, hs, prior)
    return [dict(code=int(code[f]), wi=int(wi[f]), ei=int(ei[f]), shape=sh[f]) for f in range(n)]


def _partial_1200(bits, known, prior):
    v = codec("1200")
    F = [v.unpack(b) for b in np.asarray(bits)]
    ns = len(F)
    ca = np.array([f["ca"] for f in F])
    wa = np.array([f["wa7"] for f in F])
    ea = np.array([f["ea"] for f in F])
    ha = known["ca"] & known["wa"] & known["ea"]
    ca, wa, ea = _fill_vpe(ca, wa, ea, ha)
    c = np.zeros((ns, vl.K - 1))
    hs = known["sa0"].copy()
    for s in range(ns):
        if hs[s]:
            c[s] = vq_sum(v, F[s], known, s)
    c, ok = _fill_time(c, hs)
    if not ok:
        c = prior[ca]
    A = [dict(code=int(ca[s]), wi=int(wa[s]), ei=int(ea[s]), c=c[s]) for s in range(ns)]
    out = []
    for s in range(ns):
        out.append(dict(A[s]))
        nxt = A[s + 1] if s + 1 < ns else A[s]
        if known["cb"][s] and known["dw"][s] and known["de"][s]:
            cb, dw, de = F[s]["cb"], F[s]["dw"], F[s]["de"]
        else:
            cb, dw, de = (2 if A[s]["code"] == 3 else A[s]["code"]), v.W_ZERO, v.E_ZERO
        sb = F[s]["sb"] if known["sb"][s] and ok else None
        out.append(v._b_frame(A[s], nxt, cb, dw, de, sb))
    for q in out:
        z = np.zeros(vl.K)
        z[1:] = q.pop("c")
        q["shape"] = z @ vl.DCT
    return out


def vq_sum(v, f, known, s):
    return sum(v.vq.cb[st][f[f"sa{i}"]] for i, st in enumerate(v.A_STAGES) if known[f"sa{i}"][s])


def _partial_vlr(mode, bits, known, prior):
    v = codec(mode)
    N = v.N
    F = [v.unpack(b) for b in np.asarray(bits)]
    ns = len(F)
    zs = int(np.argmin(np.abs(v.slopes)))                  # slope nearest 0
    zr = int(np.argmin((v.eres ** 2).sum(1)))              # energy residual nearest 0
    for s, f in enumerate(F):
        if not known["ws"][s]:
            f["ws"] = zs
        if not known["er"][s]:
            f["er"] = zr
    nf = ns * N
    codes = np.zeros(nf, int)
    wis = np.zeros(nf, int)
    eis = np.zeros(nf, int)
    for s, f in enumerate(F):
        fr = slice(s * N, (s + 1) * N)
        codes[fr] = v.vpat[f["v"]]
        wis[fr] = v.sf_pitch(f)
        eis[fr] = v.energy_frames(f["em"], f["er"])
    c = np.zeros((nf, vl.K - 1))
    have = np.zeros(nf, bool)
    for s, f in enumerate(F):
        for j, (off, bl) in enumerate(v.cfg["anchors"]):
            if not known[f"a{j}s0"][s]:
                continue
            c[s * N + off] = sum(v.scb[j][i][f[f"a{j}s{i}"]] for i in range(len(bl)) if known[f"a{j}s{i}"][s])
            have[s * N + off] = True
    sh = _shape_out(codes, c, have, prior)
    return [dict(code=int(codes[f]), wi=int(wis[f]), ei=int(eis[f]), shape=sh[f]) for f in range(nf)]


def decode_audio(mode, bits, known=None, prior=None):
    """Audio from superframes with the known mask (None = everything: the streamed decoder)."""
    if known is None:
        return codec(mode).decode_audio(bits)
    fp = partial_frames(mode, bits, known, prior)
    return vl.synthesise(synth()._synth(fp))


def encode(mode, x):
    return codec(mode).encode(x)
