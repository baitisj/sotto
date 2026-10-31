"""End-to-end speech test: Codec 2 2400 -> YSF payload scheme -> C4FM softmodem -> FM channel
-> softmodem receiver -> Codec 2 decoder, scored with PESQ (narrowband) and ESTOI.

Every run goes through the real receiver (sync search, flywheel, level fit), not a genie.

Usage: python sim/audio_race.py [--quick] [--samples DIR] [--out FILE] [--render DIR]
  --samples  directory of 8 kHz clips: *.flac, or <clip>__original.wav (default: $SAMPLES)
  --render   also write decoded speech for each condition and scheme as FLAC into DIR
Env:   C2BIN    directory with c2enc/c2dec (default build/codec2/src)
       HAMFLAC  hamflac binary for writing FLAC (default: on PATH, else soundfile)
"""
import argparse, glob, json, os, subprocess, sys, tempfile, time
import numpy as np
import soundfile as sf
from pesq import pesq
from pystoi import stoi

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import waveforms as wf
from audio_io import write_flac
import c4fm_sim as cs
from modem.link import Transmitter, Receiver
from modem.payload import SCHEMES

C2BIN = os.environ.get("C2BIN", os.path.join(os.path.dirname(HERE), "build", "codec2", "src"))
SAMPLES = os.environ.get("SAMPLES", "/mnt/project-files/vocoder/samples")
CLIPS = ["hts1a", "hts2a", "kristoff", "ve9qrp_10s"]


def load_clips(d):
    """-> {name: 8 kHz float array}. FLAC files if any, else the <clip>__original.wav set."""
    flac = sorted(glob.glob(os.path.join(d, "*.flac")))
    paths = {os.path.splitext(os.path.basename(f))[0]: f for f in flac} or \
        {c: os.path.join(d, f"{c}__original.wav") for c in CLIPS}
    out = {}
    for name, f in paths.items():
        x, fs = sf.read(f)
        assert fs == 8000, f"{f}: need 8 kHz"
        out[name] = x
    return out
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


CODEC_DELAY = 160     # samples; Codec 2 and every sotto encoder here (ESTOI peaks at 150-170)


def best_lag(r, x):
    """Delay to undo before scoring. Fixed: the codecs compared here all share Codec 2's
    framing, and per-clip searches were unreliable. Waveform correlation fails on synthetic
    phase, and even envelope matching wanders by +-20 samples. That moved PESQ by up to 0.1
    and ESTOI by much more (fixed 2026-10-31)."""
    return CODEC_DELAY


def search_lag(r, x, max_lag=400):
    """Delay search for a codec with unknown delay: matches the short-time energy envelopes
    (5 ms smoothing), not the waveforms, which synthetic-phase vocoders barely follow."""
    def env(s):
        return np.log(np.convolve(s ** 2, np.ones(40) / 40, "same") + 1e-7)
    n = min(len(r), len(x))
    er, ex = env(r[:n]), env(x[:n])
    best = (-2, 0)
    for lag in range(max_lag):
        a, b = er[:n - lag] - er[:n - lag].mean(), ex[lag:n] - ex[lag:n].mean()
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


def main(quick=False, seeds=(1, 2, 3), samples=SAMPLES, render=None):
    clips = {}
    for c, x in load_clips(samples).items():
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
                        y = c2dec(fr)
                        p, e = score(v["ref"], y, v["lag"])
                        if render and conceal and sd == seeds[0]:
                            tag = cond["name"].replace(" ", "_").replace("/", "")
                            write_flac(os.path.join(render, f"{c}__{tag}__{name}.flac"), y, 8000)
                        rows.append(dict(clip=c, seed=sd, conceal=conceal, pesq=p, estoi=e,
                                         fer=float((fr != v["bits"]).any(1).mean()) if not conceal else None))
            agg = {}
            for conceal in (False, True):
                rr = [r for r in rows if r["conceal"] == conceal]
                agg["conceal" if conceal else "raw"] = dict(
                    pesq=float(np.mean([r["pesq"] for r in rr])), estoi=float(np.mean([r["estoi"] for r in rr])))
            agg["fer"] = float(np.mean([r["fer"] for r in rows if r["fer"] is not None]))
            agg["per_clip"] = {c: dict(
                pesq=float(np.mean([r["pesq"] for r in rows if r["clip"] == c and r["conceal"]])),
                estoi=float(np.mean([r["estoi"] for r in rows if r["clip"] == c and r["conceal"]])))
                for c in clips}
            results["runs"].append(dict(cond=cond["name"], scheme=name, **agg, rows=rows))
            print(json.dumps(dict(cond=cond["name"], scheme=name, sec=round(time.time() - t, 1),
                                  fer=round(agg["fer"], 4),
                                  pesq_raw=round(agg["raw"]["pesq"], 2), pesq_conceal=round(agg["conceal"]["pesq"], 2),
                                  estoi_conceal=round(agg["conceal"]["estoi"], 3))), flush=True)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--samples", default=SAMPLES)
    ap.add_argument("--out")
    ap.add_argument("--render")
    a = ap.parse_args()
    if a.render:
        os.makedirs(a.render, exist_ok=True)
        for c, x in load_clips(a.samples).items():
            write_flac(os.path.join(a.render, f"{c}__original.flac"), x, 8000)
            write_flac(os.path.join(a.render, f"{c}__codec2_2400_no_channel.flac"),
                       c2dec(c2enc(np.round(x * 32767))), 8000)
    res = main(a.quick, samples=a.samples, render=a.render)
    out = a.out or os.path.join(os.path.dirname(HERE), "docs", "results",
                                "audio_race_quick.json" if a.quick else "audio_race.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print("wrote", out)
