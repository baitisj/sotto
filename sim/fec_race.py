"""First-cut FEC race for a 48-bit / 20 ms vocoder frame in a 72-bit DN-style voice slot,
over a simulated C4FM link with lmr60-style two-path Rayleigh fading.

Schemes (all 48 info bits -> 72 channel bits per 20 ms):
  conv1   K=7 (133,171) rate 1/2 punctured to 2/3, continuous, soft Viterbi, no extra interleave
  conv4   same + 4-frame (80 ms) bit interleaver
  rs8g    6 x RS(12,8) over GF(256) across an 8-frame (160 ms) superframe, errors+erasures,
          erasure gate from locally estimated noise variance
  rs8     same without gate (errors only)
  rs4g    6 x RS(6,4) across a 4-frame (80 ms) superframe, with gate
  rep     24 class-A bits sent in frame n and again in frame n+1 (soft-combined), 24 class-B once
  unc     reference: class-A bits read from first copy only (no protection)
Class A = first 24 info bits (in RS: data bytes 0-2). A frame is "bad" if any class-A bit is wrong
or (RS) its class-A bytes sit in a failed codeword. RS success uses the bounded-distance rule
e + 2t <= n-k (miscorrection ignored).
"""
import numpy as np, sys, json, time
sys.path.insert(0, '.')
import c4fm_sim as cs

SYM_PER_FRAME = 96
VOICE_SYMS = (np.arange(36) * SYM_PER_FRAME) // 36   # 36 dibits spread over the 20 ms frame
G0, G1 = 0o133, 0o171


def parity(x):
    x = np.asarray(x)
    p = np.zeros_like(x)
    while np.any(x):
        p ^= x & 1
        x = x >> 1
    return p


def conv_encode(u):
    reg = 0
    out = np.zeros((len(u), 2), np.int8)
    for i, b in enumerate(u):
        reg = ((reg << 1) | int(b)) & 127
        out[i, 0] = bin(reg & G0).count('1') & 1
        out[i, 1] = bin(reg & G1).count('1') & 1
    return out


# puncture: per pair of info bits keep g0,g1 of first, g0 of second -> 3 of 4
PUNCT = np.array([[1, 1], [1, 0]], bool)


def puncture(out):
    o = out.reshape(-1, 2, 2)
    return o[:, PUNCT].reshape(-1)


def depuncture_llr(llr, n_info):
    full = np.zeros((n_info // 2, 2, 2))
    full[:, PUNCT] = llr.reshape(-1, 3)
    return full.reshape(-1, 2)


_n = np.arange(64)
_u = _n & 1
_pred = np.stack([_n >> 1, (_n >> 1) | 32])                 # 2 x 64
_reg = ((_pred << 1) | _u) & 127
_o0 = parity(_reg & G0)
_o1 = parity(_reg & G1)
_s0 = 1 - 2 * _o0.astype(float)
_s1 = 1 - 2 * _o1.astype(float)


def viterbi(llr2):
    """llr2: (N,2) LLRs (>0 => bit 0), zeros for punctured. Returns decoded bits."""
    N = len(llr2)
    pm = np.full(64, -1e9)
    pm[0] = 0.0
    dec = np.zeros((N, 64), np.uint8)
    for i in range(N):
        a, b = llr2[i]
        cand = pm[_pred] + _s0 * a + _s1 * b              # 2 x 64
        ch = cand[1] > cand[0]
        dec[i] = ch
        pm = np.where(ch, cand[1], cand[0])
        pm -= pm.max()
    s = int(np.argmax(pm))
    out = np.zeros(N, np.int8)
    for i in range(N - 1, -1, -1):
        out[i] = s & 1
        s = int(_pred[dec[i, s], s])
    return out


def channel_run(slot_bits, n_frames, cond, seed):
    """slot_bits: (n_frames,72). Fill other symbols randomly, simulate, return per-slot-bit
    hard bits, LLRs, and per-slot-symbol noise variance."""
    rng = np.random.default_rng(seed + 12345)
    allbits = rng.integers(0, 2, (n_frames, SYM_PER_FRAME, 2)).astype(np.int8)
    allbits[:, VOICE_SYMS, :] = slot_bits.reshape(n_frames, 36, 2)
    lv = cs.bits_to_levels(allbits.reshape(-1))
    o = cs.simulate(lv, cond['ebn0'], fd=cond['fd'], tau_s=cond['tau'], two_path=cond['two_path'], seed=seed)
    hb, llr, s2 = cs.soft_demod(o['y'])
    hb = hb.reshape(n_frames, SYM_PER_FRAME, 2)[:, VOICE_SYMS, :].reshape(n_frames, 72)
    llr = llr.reshape(n_frames, SYM_PER_FRAME, 2)[:, VOICE_SYMS, :].reshape(n_frames, 72)
    s2v = s2.reshape(n_frames, SYM_PER_FRAME)[:, VOICE_SYMS]
    allhb = cs.soft_demod(o['y'])[0]
    raw_err = (allhb != allbits.reshape(-1)).reshape(-1, 2).any(1)   # per-symbol error, all symbols
    return hb, llr, s2v, raw_err, o['gain']


def burst_stats(err, gap=8):
    """Run-length stats of symbol errors; bursts = errors separated by < gap error-free symbols.
    Also a two-state Gilbert-Elliott fit (bad state = inside a burst)."""
    idx = np.flatnonzero(err)
    if len(idx) == 0:
        return {"ser": 0.0}
    br = np.flatnonzero(np.diff(idx) >= gap)
    starts = np.concatenate([[idx[0]], idx[br + 1]])
    ends = np.concatenate([idx[br], [idx[-1]]])
    lens = ends - starts + 1
    bad = np.zeros(len(err), bool)
    for s, e in zip(starts, ends):
        bad[s:e + 1] = True
    nb = bad.sum(); ng = len(err) - nb
    p_gb = len(starts) / max(ng, 1)          # good->bad per symbol
    p_bg = len(starts) / max(nb, 1)          # bad->good per symbol
    return {"ser": float(err.mean()),
            "bursts_per_s": len(starts) / (len(err) / cs.RS),
            "burst_len_sym_mean": float(lens.mean()),
            "burst_len_sym_p90": float(np.percentile(lens, 90)),
            "burst_len_ms_p90": float(np.percentile(lens, 90) / cs.RS * 1e3),
            "ge_p_gb": p_gb, "ge_p_bg": p_bg,
            "ge_err_good": float(err[~bad].mean()) if ng else 0.0,
            "ge_err_bad": float(err[bad].mean())}


def run_lengths(bad):
    """distribution of consecutive bad-frame runs: fraction of runs of length 1,2,>=3"""
    if not bad.any():
        return [0, 0, 0]
    d = np.diff(np.concatenate([[0], bad.astype(int), [0]]))
    L = np.flatnonzero(d == -1) - np.flatnonzero(d == 1)
    return [int((L == 1).sum()), int((L == 2).sum()), int((L >= 3).sum())]


def rs_eval(byte_err, byte_era, nsf, k, use_gate):
    """byte_err/era: (n_frames, 9). Superframe of nsf frames, 6 codewords RS(k+npar, k)
    with k = nsf data symbols. Returns per-frame bad flag for class-A bytes 0-2."""
    n_frames = byte_err.shape[0] // nsf * nsf
    npar = (3 * nsf) // 6   # parity symbols per codeword (4 for 8 frames, 2 for 4)
    bad = np.zeros(n_frames, bool)
    for sf in range(0, n_frames, nsf):
        E = byte_err[sf:sf + nsf]; R = byte_era[sf:sf + nsf] if use_gate else np.zeros_like(E)
        for c in range(6):
            pos = [(f, c) for f in range(nsf)]
            for j in range(npar):
                s = c * npar + j
                pos.append((s // 3, 6 + s % 3))
            e = sum(R[f, b] for f, b in pos)
            t = sum(E[f, b] and not R[f, b] for f, b in pos)
            if e + 2 * t > npar and c < 3:
                for f in range(nsf):
                    bad[sf + f] = True
    return bad


def run_condition(cond, n_frames=3000, seed=1, gate_thr=0.35):
    rng = np.random.default_rng(seed)
    info = rng.integers(0, 2, (n_frames, 48)).astype(np.int8)
    res = {}
    # --- convolutional ---
    u = info.reshape(-1)
    coded = puncture(conv_encode(u)).reshape(n_frames, 72)
    for name, D in (("conv1", 1), ("conv4", 4)):
        nf = n_frames // D * D
        if D == 1:
            slot = coded[:nf]
        else:
            blk = coded[:nf].reshape(nf // D, D * 72)
            slot = np.zeros_like(blk)
            i = np.arange(D * 72)
            slot[:, (i % D) * 72 + i // D] = blk
            slot = slot.reshape(nf, 72)
        hb, llr, s2v, raw_err, gain = channel_run(slot, nf, cond, seed)
        if D > 1:
            l2 = llr.reshape(nf // D, D * 72)
            i = np.arange(D * 72)
            llr = l2[:, (i % D) * 72 + i // D].reshape(nf, 72)
        dec = viterbi(depuncture_llr(llr.reshape(-1), nf * 48)).reshape(nf, 48)
        errs = dec != info[:nf]
        bad = errs[:, :24].any(1)
        res[name] = {"bad_frame": float(bad.mean()), "classB_ber": float(errs[:, 24:].mean()),
                     "runs_1_2_3plus": run_lengths(bad)}
        if name == "conv1":
            res["raw"] = burst_stats(raw_err)
            res["raw"]["slot_ber"] = float((hb != slot).mean())
            res["raw"]["fade_below_-10dB"] = float((gain < 0.1).mean())
    # --- RS family: byte-level error/erasure from one channel run with random slot bits ---
    slot = rng.integers(0, 2, (n_frames, 72)).astype(np.int8)
    hb, llr, s2v, _, gsym = channel_run(slot, n_frames, cond, seed)
    berr = (hb != slot).reshape(n_frames, 9, 8).any(2)
    best = None
    for thr in (0.25, 0.35, 0.5, 0.8, 1.5, 3.0):
        era = (s2v.reshape(n_frames, 9, 4) > thr).any(2)
        b8 = rs_eval(berr, era, 8, 8, True)
        if best is None or b8.mean() < best[1].mean():
            best = (thr, b8, era)
    thr, b8, bera = best
    res["rs8g"] = {"bad_frame": float(b8.mean()), "gate_thr": thr, "runs_1_2_3plus": run_lengths(b8)}
    res["rs8"] = {"bad_frame": float(rs_eval(berr, bera, 8, 8, False).mean())}
    b4 = rs_eval(berr, bera, 4, 4, True)
    res["rs4g"] = {"bad_frame": float(b4.mean()), "runs_1_2_3plus": run_lengths(b4)}
    res["rs8_perfect_erasures"] = {"bad_frame": float(rs_eval(berr, berr, 8, 8, True).mean())}
    gv = gsym.reshape(n_frames, SYM_PER_FRAME)[:, VOICE_SYMS].reshape(n_frames, 9, 4).min(2)
    bc = min((rs_eval(berr, gv < g, 8, 8, True).mean(), g) for g in (0.03, 0.06, 0.1, 0.2, 0.3))
    res["rs8_csi_gate"] = {"bad_frame": float(bc[0]), "gain_thr": bc[1]}
    res["gate"] = {"thr": thr, "erased_bytes": float(bera.mean()),
                   "err_bytes_caught": float((berr & bera).sum() / max(berr.sum(), 1)),
                   "byte_err_rate": float(berr.mean())}
    # --- repetition of class A in next frame ---
    A = info[:, :24]; B = info[:, 24:]
    prevA = np.vstack([np.zeros((1, 24), np.int8), A[:-1]])
    slot = np.hstack([A, B, prevA])
    hb, llr, _, _, _ = channel_run(slot, n_frames, cond, seed)
    comb = llr[:, :24].copy(); comb[:-1] += llr[1:, 48:]
    decA = (comb < 0).astype(np.int8)
    bad = (decA[:-1] != A[:-1]).any(1)
    res["rep"] = {"bad_frame": float(bad.mean()), "classB_ber": float((hb[:, 24:48] != B).mean()),
                  "runs_1_2_3plus": run_lengths(bad)}
    res["unc"] = {"bad_frame": float((hb[:, :24] != A).any(1).mean())}
    return res


def main():
    conds = []
    for band in (146e6, 446e6):
        for kmh in (30, 60, 120):
            for e in (15, 20, 25):
                conds.append(dict(name=f"{int(band/1e6)}MHz {kmh}km/h {e}dB flat", band=band, kmh=kmh, ebn0=e,
                                  fd=cs.doppler(band, kmh), tau=0.0, two_path=False))
    for tau in (5e-6, 10e-6, 25e-6, 50e-6, 100e-6, 200e-6):
        conds.append(dict(name=f"2-path {int(tau*1e6)}us 446MHz 60km/h 25dB", band=446e6, kmh=60, ebn0=25,
                          fd=cs.doppler(446e6, 60), tau=tau, two_path=True))
    for e in (8, 10, 12):
        conds.append(dict(name=f"AWGN static {e}dB", band=0, kmh=0, ebn0=e, fd=0, tau=0, two_path=False))
    which = sys.argv[1:] and [int(x) for x in sys.argv[1:]] or range(len(conds))
    out = []
    for i in which:
        c = conds[i]; t = time.time()
        r = run_condition(c)
        r["cond"] = c
        out.append(r)
        print(json.dumps({"i": i, "name": c["name"], "sec": round(time.time() - t, 1),
                          **{k: round(v["bad_frame"], 4) for k, v in r.items() if isinstance(v, dict) and "bad_frame" in v},
                          "ser": round(r["raw"]["ser"], 4)}), flush=True)
    with open(f"results_{'_'.join(map(str, which)) if sys.argv[1:] else 'all'}.json", "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
