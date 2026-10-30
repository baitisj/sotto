"""End-to-end speech test: Codec 2 2400 -> YSF payload scheme -> C4FM softmodem -> FM channel
-> softmodem receiver -> Codec 2 decoder, scored with PESQ (narrowband) and ESTOI.

Every run goes through the real receiver (sync search, flywheel, level fit), not a genie.

Usage: python sim/audio_race.py [--quick]
Env:   C2BIN    directory with c2enc/c2dec (default build/codec2/src)
       SAMPLES  directory with <clip>__original.wav at 8 kHz
"""
import json, os, subprocess, sys, tempfile, time
import numpy as np
import soundfile as sf
from pesq import pesq
from pystoi import stoi

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import waveforms as wf
import c4fm_sim as cs
from modem.link import Transmitter, Receiver
from modem.payload import SCHEMES

C2BIN = os.environ.get("C2BIN", os.path.join(os.path.dirname(HERE), "build", "codec2", "src"))
SAMPLES = os.environ.get("SAMPLES", "/mnt/project-files/vocoder/samples")
CLIPS = ["hts1a", "hts2a", "kristoff", "ve9qrp_10s"]
LEAD = 2400                      # modulator lead-in (samples at 48 kHz)


def c2enc(x16):
    with tempfile.TemporaryDirectory() as d:
        (x16.astype("<i2")).tofile(f"{d}/in.raw")
        subprocess.run([f"{C2BIN}/c2enc", "2400", f"{d}/in.raw", f"{d}/out.bit"], check=True)
        b = np.fromfile(f"{d}/out.bit", np.uint8)
    return np.unpackbits(b).reshape(-1, 48).astype(np.int8)


def c2dec(bits):
    with tempfile.TemporaryDirectory() as d:
        np.packbits(bits.astype(np.uint8).reshape(-1)).tofile(f"{d}/in.bit")
        subprocess.run([f"{C2BIN}/c2dec", "2400", f"{d}/in.bit", f"{d}/out.raw"], check=True)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


def best_lag(r, x, max_lag=400):
    n = min(len(r), len(x))
    best = (-2, 0)
    for lag in range(max_lag):
        a, b = r[:n - lag], x[lag:n]
        c = np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b) + 1e-9)
        best = max(best, (c, lag))
    return best[1]


def score(ref, out, lag):
    n = min(len(ref), len(out) - lag)
    r, x = ref[:n], out[lag:lag + n]
    try:
        p = pesq(8000, r, x, "nb")
    except Exception:
        p = 1.0
    return p, stoi(r, x, 8000, extended=True)


def conditions(quick=False):
    c = [dict(name="AWGN 46 dB-Hz", cn0=46, fd=0.0),
         dict(name="AWGN 48 dB-Hz", cn0=48, fd=0.0),
         dict(name="146 MHz 30 km/h 52 dB-Hz", cn0=52, fd=cs.doppler(146e6, 30)),
         dict(name="146 MHz 30 km/h 56 dB-Hz", cn0=56, fd=cs.doppler(146e6, 30)),
         dict(name="446 MHz 60 km/h 48 dB-Hz", cn0=48, fd=cs.doppler(446e6, 60)),
         dict(name="446 MHz 60 km/h 52 dB-Hz", cn0=52, fd=cs.doppler(446e6, 60)),
         dict(name="446 MHz 60 km/h 56 dB-Hz", cn0=56, fd=cs.doppler(446e6, 60))]
    return c[::3] if quick else c


def main(quick=False, seeds=(1, 2, 3)):
    clips = {}
    for c in CLIPS:
        x, fs = sf.read(f"{SAMPLES}/{c}__original.wav")
        assert fs == 8000
        bits = c2enc(np.round(x * 32767))
        clean = c2dec(bits)
        lag = best_lag(x, clean)
        clips[c] = dict(ref=x, bits=bits, lag=lag, clean=score(x, clean, lag))
    results = {"codec_only": {c: v["clean"] for c, v in clips.items()}, "runs": []}
    print("codec only (PESQ/ESTOI):", {c: tuple(round(s, 2) for s in v["clean"]) for c, v in clips.items()})
    seeds = seeds[:1] if quick else seeds
    for cond in conditions(quick):
        for name in SCHEMES:
            t = time.time()
            rows = []
            for c, v in clips.items():
                tx = Transmitter(name).modulate(v["bits"])
                t0 = LEAD + 4800                          # first voice frame (after the header)
                for sd in seeds:
                    disc, _ = wf.fm_channel(tx, cond["cn0"], fd=cond["fd"], seed=sd * 100 + len(c))
                    rx = Receiver(name).receive(disc, t0=t0)
                    n = len(v["bits"])
                    for conceal in (False, True):
                        fr = rx["frames"] if conceal else rx["raw_frames"]
                        fr = np.concatenate([fr, np.zeros((max(0, n - len(fr)), 48), np.int8)])[:n]
                        p, e = score(v["ref"], c2dec(fr), v["lag"])
                        rows.append(dict(clip=c, seed=sd, conceal=conceal, pesq=p, estoi=e,
                                         fer=float((fr != v["bits"]).any(1).mean()) if not conceal else None))
            agg = {}
            for conceal in (False, True):
                rr = [r for r in rows if r["conceal"] == conceal]
                agg["conceal" if conceal else "raw"] = dict(
                    pesq=float(np.mean([r["pesq"] for r in rr])), estoi=float(np.mean([r["estoi"] for r in rr])))
            agg["fer"] = float(np.mean([r["fer"] for r in rows if r["fer"] is not None]))
            results["runs"].append(dict(cond=cond["name"], scheme=name, **agg, rows=rows))
            print(json.dumps(dict(cond=cond["name"], scheme=name, sec=round(time.time() - t, 1),
                                  fer=round(agg["fer"], 4),
                                  pesq_raw=round(agg["raw"]["pesq"], 2), pesq_conceal=round(agg["conceal"]["pesq"], 2),
                                  estoi_conceal=round(agg["conceal"]["estoi"], 3))), flush=True)
    return results


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    res = main(quick)
    out = os.path.join(os.path.dirname(HERE), "docs", "results", "audio_race_quick.json" if quick else "audio_race.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print("wrote", out)
