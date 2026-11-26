"""Embed the ID frame in a clip, send it through the simulated FM channels, decode it, and
report raw bit errors, usable slots and the time to the first correct ID decode.

python watermark/run.py CLIP.flac [--strength 1.0] [--nsub 2] [--out DIR]
"""
import argparse, json, os, sys
import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harmonic as hm, fmchan as fc, fec

CHANNELS = {
    "clean":          dict(kind="clean"),
    "bandpass":       dict(kind="bandpass"),
    "simplex-25dB":   dict(kind="simplex", cnr_in=25),
    "repeater-40dB":  dict(kind="repeater", cnr_in=40, cnr_out=40),
    "repeater-25dB":  dict(kind="repeater", cnr_in=25, cnr_out=25),
    "repeater-hot":   dict(kind="repeater", cnr_in=25, cnr_out=25, drive_db=6),
    "repeater-15dB":  dict(kind="repeater", cnr_in=15, cnr_out=25),
    "repeater-10dB":  dict(kind="repeater", cnr_in=10, cnr_out=25),
}


def receive(z, p, code, tx_used=None, tx_bits=None, step=8):
    R, est = hm.Receiver(z, p).read()
    res = {"offset": int(est["offset"]), "phase_deg": est["phase_deg"]}
    live = np.abs(R).sum(1) > 0
    res["rx_voiced_slots"] = float(live.mean())
    if tx_used is not None:
        n = min(len(R), len(tx_used))
        ok = live[:n] & tx_used[:n]
        err = (R[:n][ok] < 0) != tx_bits[:n][ok].astype(bool)
        res["both_slots"] = float(ok.mean())
        res["raw_ber"] = float(err.mean()) if ok.any() else None
        slot_s = p.slot / hm.FS
        res["raw_bps"] = float(ok.sum() * p.nsub / (n * slot_s))
    # time to the first correct decode, trying every `step` slots as audio arrives
    # an ID counts once the same frame (content and start) decodes twice running
    res["first_decode_s"] = None
    res["wrong_decodes"] = 0
    prev = None
    for m in range(step, len(R) + 1, step):
        got = code.decode(R[:m])
        if got is not None and prev is not None and got[:3] == prev[:3]:
            if got[:2] == (fec.unpack_call(fec.pack_call("AG7EW")), code_value(code)):
                res["first_decode_s"] = round(m * p.slot / hm.FS, 2)
                res["quality"] = got[3]
                break
            res["wrong_decodes"] += 1
        prev = got
    return res


def code_value(code):
    return fec._val(code.msg[32:40])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--nsub", type=int, default=4)
    ap.add_argument("--slot", type=int, default=256)
    ap.add_argument("--band", default="500,2600")
    ap.add_argument("--channels", default=",".join(CHANNELS))
    ap.add_argument("--control", action="store_true", help="also decode the unmarked clip")
    ap.add_argument("--out")
    a = ap.parse_args()
    x, fs = sf.read(a.clip)
    assert fs == hm.FS
    p = hm.Params(strength=a.strength, nsub=a.nsub, slot=a.slot,
                  band=tuple(float(v) for v in a.band.split(",")))
    code = fec.Code(nsub=p.nsub)
    y, info = hm.embed(x, code.bits_for_slot, p)
    used = info["slots"]
    bits = np.array([code.bits_for_slot(j) for j in range(len(used))])
    out = {"clip": os.path.basename(a.clip), "strength": p.strength, "nsub": p.nsub,
           "slot_ms": p.slot * 1000 / hm.FS, "band": p.band,
           "tx_slots": float(used.mean()), "channels": {}}
    try:
        from pesq import pesq
        out["pesq_nb_marked"] = round(float(pesq(hm.FS, x, y, "nb")), 3)
    except ImportError:
        pass
    for name in a.channels.split(","):
        z, cinfo = fc.channel(y, **CHANNELS[name])
        r = receive(z, p, code, used, bits)
        r.update({k: round(float(v), 4) for k, v in cinfo.items()})
        if a.control:
            zc, _ = fc.channel(x, **CHANNELS[name])
            rc = receive(zc, p, code)
            r["control_first_decode_s"] = rc["first_decode_s"]
            r["control_wrong_decodes"] = rc["wrong_decodes"]
        out["channels"][name] = r
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            sf.write(os.path.join(a.out, f"{name}.wav"), z / max(1, np.abs(z).max()), hm.FS,
                     subtype="PCM_16")
        print(name, json.dumps(r), flush=True)
    if a.out:
        sf.write(os.path.join(a.out, "marked.wav"), y, hm.FS, subtype="PCM_16")
        with open(os.path.join(a.out, "result.json"), "w") as f:
            json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "channels"}))


if __name__ == "__main__":
    main()
