"""Race baseband-over-FM waveforms for a 2400 bps vocoder + rate-2/3 conv code (3600 bps).

All waveforms carry the same coded stream: 48 info bits / 20 ms -> K=7 code punctured to
rate 2/3 -> 72 bits / 20 ms -> 4-frame (80 ms) block interleaver. Noise is set by C/N0
(equal transmitted power). Metric: class-A (first 24 bits) bad-frame rate and class-B BER.

Usage: python waveform_race.py [condition indices...]   (no args = all)
"""
import json, sys, time
import numpy as np
import c4fm_sim as cs
import waveforms as wf
from fec_race import conv_encode, puncture, depuncture_llr, viterbi, VOICE_SYMS, SYM_PER_FRAME

D = 4  # interleaver depth (frames)

WAVES = {
    "c4fm_dn": wf.FSK("c4fm_dn", 4800, [600, 1800], 2, 3000, voice_frac=36 / 96),
    "fsk4_1800": wf.FSK("fsk4_1800", 1800, [600, 1800], 2, 1200, fs=43200),
    "fsk2_3600": wf.FSK("fsk2_3600", 3600, [1800], 1, 2400, fs=43200),
    "ofdm": wf.OFDM(),
}
def interleave(coded, nf):
    blk = coded[:nf].reshape(nf // D, D * 72)
    out = np.zeros_like(blk)
    i = np.arange(D * 72)
    out[:, (i % D) * 72 + i // D] = blk
    return out.reshape(nf, 72)


def deinterleave(llr, nf):
    l2 = llr.reshape(nf // D, D * 72)
    i = np.arange(D * 72)
    return l2[:, (i % D) * 72 + i // D].reshape(nf, 72)


def run_wave(name, slot, nf, cond, seed):
    w = WAVES[name]
    cn0 = cond["cn0"]
    kw = dict(fd=cond["fd"], tau_s=cond["tau"], two_path=cond["two_path"], seed=seed,
              fs=getattr(w, "fs", wf.FS))
    if name == "c4fm_dn":
        rng = np.random.default_rng(seed + 99)
        allbits = rng.integers(0, 2, (nf, SYM_PER_FRAME, 2)).astype(np.int8)
        allbits[:, VOICE_SYMS, :] = slot.reshape(nf, 36, 2)
        f, ns = w.modulate(allbits.reshape(-1))
        disc, _ = wf.fm_channel(f, cn0, **kw)
        _, llr = w.demod(disc, ns)
        return llr.reshape(nf, SYM_PER_FRAME, 2)[:, VOICE_SYMS, :].reshape(nf, 72)
    bits = slot.reshape(-1)
    if name == "ofdm":
        f, meta = w.modulate(bits)
        disc, _ = wf.fm_channel(f, cn0, **kw)
        _, llr = w.demod(disc, meta)
        return llr.reshape(nf, 72)
    f, ns = w.modulate(bits)
    disc, _ = wf.fm_channel(f, cn0, **kw)
    _, llr = w.demod(disc, ns)
    return llr[:len(bits)].reshape(nf, 72)


def run_condition(cond, nf=2000, seed=3):
    rng = np.random.default_rng(seed)
    info = rng.integers(0, 2, (nf, 48)).astype(np.int8)
    coded = puncture(conv_encode(info.reshape(-1))).reshape(nf, 72)
    slot = interleave(coded, nf)
    res = {}
    for name in WAVES:
        llr = run_wave(name, slot, nf, cond, seed)
        raw = float(((llr < 0).astype(np.int8) != slot).mean())
        dec = viterbi(depuncture_llr(deinterleave(llr, nf).reshape(-1), nf * 48)).reshape(nf, 48)
        err = dec != info
        res[name] = {"bad_frame": float(err[:, :24].any(1).mean()),
                     "classB_ber": float(err[:, 24:].mean()), "raw_ber": raw}
    return res


def conditions():
    c = []
    for e in (42, 44, 46, 48):
        c.append(dict(name=f"AWGN {e}dBHz", cn0=e, fd=0, tau=0, two_path=False))
    for band, kmh in ((146e6, 30), (146e6, 60), (446e6, 60), (446e6, 120)):
        for e in (48, 52, 56, 60):
            c.append(dict(name=f"{int(band/1e6)}MHz {kmh}km/h {e}dBHz", band=band, kmh=kmh, cn0=e,
                          fd=cs.doppler(band, kmh), tau=0.0, two_path=False))
    for tau in (10e-6, 25e-6, 50e-6, 100e-6, 200e-6):
        c.append(dict(name=f"2-path {int(tau*1e6)}us 446MHz 60km/h 60dBHz", band=446e6, kmh=60, cn0=60,
                      fd=cs.doppler(446e6, 60), tau=tau, two_path=True))
    return c


if __name__ == "__main__":
    C = conditions()
    idx = [int(a) for a in sys.argv[1:]] or range(len(C))
    out = []
    for i in idx:
        t = time.time()
        r = run_condition(C[i])
        r["cond"] = C[i]
        out.append(r)
        print(json.dumps({"i": i, "name": C[i]["name"], "sec": round(time.time() - t, 1),
                          **{k: round(v["bad_frame"], 4) for k, v in r.items() if k != "cond"},
                          "raw": {k: round(v["raw_ber"], 4) for k, v in r.items() if k != "cond"}}), flush=True)
    with open(f"wave_results_{'_'.join(map(str, idx))}.json", "w") as f:
        json.dump(out, f, indent=1)
