"""Extra race entry: keep Yaesu C4FM framing but use the VW (full-rate) voice slot.

VW leaves 7200 of every 9600 bps for voice (72 of 96 symbols per 20 ms), so a 2400 bps
vocoder can use a K=7 rate-1/3 code (133,171,165): 48 info bits -> 144 coded bits / 20 ms,
plus the same 4-frame (80 ms) interleaver. Same conditions and metrics as waveform_race.py.
"""
import json, sys, time
import numpy as np
import waveforms as wf
from fec_race import SYM_PER_FRAME
from waveform_race import conditions

G = (0o133, 0o171, 0o165)
NB = 144
D = 4
VW_SYMS = (np.arange(72) * SYM_PER_FRAME) // 72


def enc3(u):
    reg = 0
    out = np.zeros((len(u), 3), np.int8)
    for i, b in enumerate(u):
        reg = ((reg << 1) | int(b)) & 127
        for j, g in enumerate(G):
            out[i, j] = bin(reg & g).count("1") & 1
    return out


_n = np.arange(64)
_pred = np.stack([_n >> 1, (_n >> 1) | 32])
_reg = ((_pred << 1) | (_n & 1)) & 127
_S = [1 - 2 * np.array([[bin(r & g).count("1") & 1 for r in row] for row in _reg], float) for g in G]


def vit3(llr):
    N = len(llr)
    pm = np.full(64, -1e9); pm[0] = 0
    dec = np.zeros((N, 64), np.uint8)
    for i in range(N):
        cand = pm[_pred] + _S[0] * llr[i, 0] + _S[1] * llr[i, 1] + _S[2] * llr[i, 2]
        ch = cand[1] > cand[0]
        dec[i] = ch
        pm = np.where(ch, cand[1], cand[0]); pm -= pm.max()
    s = int(np.argmax(pm)); out = np.zeros(N, np.int8)
    for i in range(N - 1, -1, -1):
        out[i] = s & 1; s = int(_pred[dec[i, s], s])
    return out


def run_condition(cond, nf=2000, seed=3):
    rng = np.random.default_rng(seed)
    info = rng.integers(0, 2, (nf, 48)).astype(np.int8)
    coded = enc3(info.reshape(-1)).reshape(nf, NB)
    blk = coded.reshape(nf // D, D * NB); i = np.arange(D * NB)
    slot = np.zeros_like(blk); slot[:, (i % D) * NB + i // D] = blk; slot = slot.reshape(nf, NB)
    w = wf.FSK("c4fm_vw", 4800, [600, 1800], 2, 3000)
    allbits = np.random.default_rng(seed + 99).integers(0, 2, (nf, SYM_PER_FRAME, 2)).astype(np.int8)
    allbits[:, VW_SYMS, :] = slot.reshape(nf, 72, 2)
    f, ns = w.modulate(allbits.reshape(-1))
    disc, _ = wf.fm_channel(f, cond["cn0"], fd=cond["fd"], tau_s=cond["tau"], two_path=cond["two_path"], seed=seed)
    _, llr = w.demod(disc, ns)
    llr = llr.reshape(nf, SYM_PER_FRAME, 2)[:, VW_SYMS, :].reshape(nf, NB)
    raw = float(((llr < 0).astype(np.int8) != slot).mean())
    l2 = llr.reshape(nf // D, D * NB)[:, (i % D) * NB + i // D].reshape(-1, 3)
    dec = vit3(l2).reshape(nf, 48)
    err = dec != info
    return {"c4fm_vw": {"bad_frame": float(err[:, :24].any(1).mean()),
                        "classB_ber": float(err[:, 24:].mean()), "raw_ber": raw}}


if __name__ == "__main__":
    C = conditions()
    idx = [int(a) for a in sys.argv[1:]] or range(len(C))
    out = []
    for k in idx:
        t = time.time(); r = run_condition(C[k]); r["cond"] = C[k]; out.append(r)
        print(json.dumps({"i": k, "name": C[k]["name"], "sec": round(time.time() - t, 1),
                          "c4fm_vw": round(r["c4fm_vw"]["bad_frame"], 4)}), flush=True)
    with open(f"vw_results_{'_'.join(map(str, idx))}.json", "w") as f:
        json.dump(out, f, indent=1)
