"""Over-the-air test through the Pluto: build the FM modulating WAVs, then read what came back.

  python watermark/ota.py prep OUTDIR CLIP.flac [CLIP.flac ...]
      OUTDIR/marked.wav: each clip watermarked (ID frame, default Params), pre-emphasised and
      limited as a radio's transmitter does (fmchan.tx_audio), 1 s of silence between clips,
      full scale = peak deviation (send it with pluto_bench.py send/steps --dev 2500 and no
      --preemph). OUTDIR/clean.wav: the same clips unmarked (the control).
      OUTDIR/layout.json: where each clip sits.

  python watermark/ota.py read RX.wav OUTDIR/layout.json [--json OUT.json]
      RX.wav: pluto_bench.py rx --wav-only (discriminator audio, 8 kHz, full scale 5000 Hz).
      Finds each transmission by correlating with what was sent, de-emphasises and band-limits
      it as a receiver does, and decodes each clip: raw bit errors and time to the ID. With
      --audio, a radio sent OUTDIR/marked_audio.wav and clean_audio.wav (plain speech, 48 kHz)
      through its own transmit audio chain.
"""
import argparse, json, os, sys
import numpy as np
import soundfile as sf
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harmonic as hm, fmchan as fc, fec

GAP = hm.FS          # 1 s between clips


def prep(a):
    os.makedirs(a.out, exist_ok=True)
    p = hm.Params()
    code = fec.Code(nsub=p.nsub)
    marked, clean, layout, speech_m, speech_c = [], [], [], [], []
    pos = GAP
    for clip in a.clips:
        x, fs = sf.read(clip)
        assert fs == hm.FS
        y, info = hm.embed(x, code.bits_for_slot, p)
        m, _ = fc.tx_audio(y)
        mc, _ = fc.tx_audio(x)
        speech_m.append(y)
        speech_c.append(x)
        marked.append(np.clip(m, -1, 1))
        clean.append(np.clip(mc, -1, 1))
        layout.append({"clip": os.path.basename(clip), "start": pos, "n": len(x),
                       "slots": info["slots"].astype(int).tolist()})
        pos += len(x) + GAP
    z = np.zeros(GAP)
    for name, parts in (("marked", marked), ("clean", clean)):
        w = np.concatenate([z] + [np.concatenate([q, z]) for q in parts])
        sf.write(os.path.join(a.out, f"{name}.wav"), w, hm.FS, subtype="PCM_16")
    # plain speech for a radio's own transmitter (its pre-emphasis and limiter), 48 kHz, one
    # gain for both so speech peaks sit near -3 dBFS
    sp = {"marked_audio": speech_m, "clean_audio": speech_c}
    g = 0.7 / max(np.abs(np.concatenate(speech_m)).max(), np.abs(np.concatenate(speech_c)).max())
    for name, parts in sp.items():
        w = np.concatenate([z] + [np.concatenate([q, z]) for q in parts]) * g
        sf.write(os.path.join(a.out, f"{name}8k.wav"), w, hm.FS, subtype="PCM_16")
        sf.write(os.path.join(a.out, f"{name}.wav"), signal.resample_poly(w, 6, 1), 48000,
                 subtype="PCM_16")
    with open(os.path.join(a.out, "layout.json"), "w") as f:
        json.dump({"clips": layout, "dev": fc.DEV, "nsub": p.nsub}, f)
    print("wrote", a.out, [l["clip"] for l in layout])


def receiver_audio(d):
    """Discriminator audio (8 kHz, units of peak deviation) -> what a radio's speaker gets."""
    b, a = fc._emph(hm.FS, False)
    return signal.sosfilt(fc._voice_bp(hm.FS), signal.lfilter(b, a, d))


def read(a):
    lay = json.load(open(a.layout))
    d, fs = sf.read(a.rx)
    assert fs == hm.FS
    d = d * 5000.0 / lay["dev"]                 # full scale 5000 Hz -> units of peak deviation
    d = d - np.mean(d)
    base = os.path.dirname(a.layout)
    if a.audio:
        # a radio transmitted the plain speech: find it in the de-emphasised audio
        ref = signal.sosfilt(fc._voice_bp(hm.FS), sf.read(os.path.join(base, "marked_audio8k.wav"))[0])
        refc = signal.sosfilt(fc._voice_bp(hm.FS), sf.read(os.path.join(base, "clean_audio8k.wav"))[0])
        dc = receiver_audio(d)
    else:
        ref, _ = sf.read(os.path.join(base, "marked.wav"))
        refc, _ = sf.read(os.path.join(base, "clean.wav"))
        dc = d
    p = hm.Params(nsub=lay["nsub"])
    code = fec.Code(nsub=p.nsub)
    # every place a sent track shows up (correlating the flat discriminator audio with it); the
    # marked and clean tracks are the same speech, so each place is labelled by the closer one
    def ncorr(r):
        c = signal.fftconvolve(dc, r[::-1], "valid")
        return c / np.sqrt(np.sum(r ** 2) * signal.fftconvolve(dc ** 2, np.ones(len(r)), "valid") + 1e-12)
    cm, cc = ncorr(ref), ncorr(refc)
    best = np.maximum(cm, cc)
    used = np.zeros(len(best), bool)
    out = []
    for _ in range(12):
        k = int(np.argmax(np.where(used, -1, best)))
        if best[k] < 0.3:
            break
        used[max(0, k - len(ref) // 2):k + len(ref) // 2] = True
        kind = "marked" if cm[k] >= cc[k] else "clean"
        r = ref if kind == "marked" else refc
        seg = d[k:k + len(r)]
        sc = dc[k:k + len(r)]
        res = sc - r * np.dot(sc, r) / np.dot(r, r)
        item = {"kind": kind, "at_s": round(k / hm.FS, 2), "corr_marked": round(float(cm[k]), 4),
                "corr_clean": round(float(cc[k]), 4),
                "residual_db": round(float(10 * np.log10(np.mean(res ** 2) / np.mean(sc ** 2) + 1e-12)), 1),
                "clips": []}
        for cl in lay["clips"]:
            z = receiver_audio(seg)[cl["start"]:cl["start"] + cl["n"]]
            R, est = hm.Receiver(z, p).read()
            tx = np.array(cl["slots"], bool)
            n = min(len(R), len(tx))
            ok = (np.abs(R[:n]).sum(1) > 0) & tx[:n]
            bits = np.array([code.bits_for_slot(j) for j in range(n)])
            ber = float(np.mean((R[:n][ok] < 0) != bits[ok].astype(bool))) if ok.any() else None
            first, prev = None, None
            for m in range(8, len(R) + 1, 8):
                got = code.decode(R[:m])
                if got is not None and prev is not None and got[:3] == prev[:3]:
                    first = {"s": round(m * p.slot / hm.FS, 2), "call": got[0], "code": got[1]}
                    break
                prev = got
            item["clips"].append({"clip": cl["clip"], "raw_ber": ber,
                                  "raw_bps": float(ok.sum() * p.nsub / (n * p.slot / hm.FS)),
                                  "first_decode": first})
        out.append(item)
        print(json.dumps(item), flush=True)
    out.sort(key=lambda i: i["at_s"])
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prep")
    s.add_argument("out")
    s.add_argument("clips", nargs="+")
    r = sub.add_parser("read")
    r.add_argument("rx")
    r.add_argument("layout")
    r.add_argument("--json")
    r.add_argument("--audio", action="store_true",
                   help="a radio sent marked_audio.wav / clean_audio.wav itself (its own pre-emphasis)")
    a = ap.parse_args()
    prep(a) if a.cmd == "prep" else read(a)


if __name__ == "__main__":
    main()
