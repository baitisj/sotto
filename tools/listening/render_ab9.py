"""Blind A/B round 9: (a) depth-1 vs depth-2 interleaving of the VW payload on fading 2 m
(146 MHz), both decoded by v3.5 through the same fades; (b) the shipped 12+11+11 shape
codebook (v3.5) vs the 9+9+8+8 codebook rounded to 8-bit values (v3.6 candidate, 29 KB
for the C5517), no radio channel. Both use the 80 ms real-time tracker. Original in every
pair; one identical null pair.
Usage: python render_ab9.py OUT_AUDIO_DIR  (run from the sotto repo root, branch claude/c-port-interleave)"""
import sys, json, random, numpy as np, soundfile as sf
sys.path.insert(0, "sim"); sys.path.insert(0, ".")
import audio_race as ar, vocoder_lab as vl, waveforms as wf, c4fm_sim as cs
from modem.link import Transmitter, Receiver
from modem.interleave import Transmitter2, Receiver2
OUT = sys.argv[1]
SRC = {"female_libri198_14s": "/mnt/project-files/vocoder/samples15/female_libri198_14s.flac",
       "male_libri3436_15s": "/mnt/project-files/vocoder/samples15/male_libri3436_15s.flac"}
CL = "/mnt/project-files/vocoder/samples-clean"
for n in ("librispeech_3536_f", "librispeech_251_m", "librispeech_8842_f", "librispeech_777_m",
          "librispeech_6313_f", "librispeech_652_m", "ears_p047_f", "ears_p107_m", "ears_p100_f", "ears_p020_m"):
    SRC[n] = f"{CL}/{n}.flac"
def name(c):
    if c.startswith("ears"):
        return ("Female" if c.endswith("f") else "Male") + " (EARS studio)"
    sp = c.split("_")[1].replace("libri", "")
    return ("Female" if c.startswith("female") or c.endswith("_f") else "Male") + f" (LibriSpeech {sp})"
plan = [("il", "librispeech_251_m", 30, 52), ("il", "ears_p047_f", 60, 52), ("il", "male_libri3436_15s", 100, 52),
        ("il", "librispeech_3536_f", 30, 56), ("il", "ears_p107_m", 5, 52), ("il", "female_libri198_14s", 60, 52),
        ("cb", "librispeech_8842_f"), ("cb", "librispeech_777_m"), ("cb", "ears_p100_f"), ("cb", "ears_p020_m"),
        ("cb", "librispeech_6313_f"), ("null", "librispeech_652_m")]
rng = random.Random(2026103109); rng.shuffle(plan)
swaps = [True, False] * 6; rng.shuffle(swaps)
vl.TRACK2["lag"] = 8
def int8(q):
    q2 = vl.ShapeMSVQ.__new__(vl.ShapeMSVQ); q2.bits, q2.m = q.bits, 8
    q2.cb = [np.round(c / (np.abs(c).max() / 127)) * (np.abs(c).max() / 127) for c in q.cb]
    return q2
v35 = vl.SottoV35()
v36 = vl.SottoV35(vq=int8(vl.ShapeMSVQ.load("sim/data/shape_msvq_9988.npz")))
mute = np.zeros(48, np.int8)
def radio(bits, c, kmh, cn0, depth):
    n = len(bits)
    T, R = (Transmitter, Receiver) if depth == 1 else (Transmitter2, Receiver2)
    disc, _ = wf.fm_channel(T("sotto_vw").modulate(bits), cn0, fd=cs.doppler(146e6, kmh), seed=100 + len(c))
    rx = R("sotto_vw", mute=mute).receive(disc, t0=ar.LEAD + 4800)
    fr = np.concatenate([rx["frames"], np.repeat(mute[None], max(0, n - len(rx["frames"])), 0)])[:n]
    good = np.concatenate([rx["good"], np.zeros(max(0, n - len(rx["good"])), bool)])[:n]
    return vl.synthesise(v35.decode(fr, good))[ar.CODEC_DELAY:], 1 - float(good.mean())
def cut(y, s=10):
    y = y[:int(s * 8000)].copy(); f = 160
    y[:f] *= np.linspace(0, 1, f); y[-f:] *= np.linspace(1, 0, f); return y
lvl = lambda y, r: y * np.sqrt(np.mean(r ** 2) / (np.mean(y ** 2) + 1e-12))
w = lambda p, y: sf.write(p, np.round(np.clip(y, -1, 1) * 32767).astype(np.int16), 8000, subtype="PCM_16")
trials, key = [], {}
for n, item in enumerate(plan, 1):
    kind, c = item[0], item[1]
    x = sf.read(SRC[c])[0]; x = x[:len(x) // 160 * 160]; ref = cut(x)
    if kind == "il":
        kmh, cn0 = item[2], item[3]
        bits = v35.encode(x)
        (ya, la), (yb, lb) = radio(bits, c, kmh, cn0, 1), radio(bits, c, kmh, cn0, 2)
        p, q = "depth1", "depth2"
        info = dict(kmh=kmh, cn0=cn0, loss_depth1=round(la, 3), loss_depth2=round(lb, 3))
        desc = f"{name(c)}, 2 m at {kmh} km/h, {'weak' if cn0 == 52 else 'fair'} signal"
    else:
        ya = vl.synthesise(v35.decode(v35.encode(x)))[ar.CODEC_DELAY:]
        yb = vl.synthesise(v36.decode(v36.encode(x)))[ar.CODEC_DELAY:]
        p, q = "v35_12-11-11", "v36_9-9-8-8_int8"
        if kind == "null":
            ya, p = yb, q
        info = {}
        desc = f"{name(c)}, no radio channel"
    a, b = lvl(cut(ya), ref), lvl(cut(yb), ref)
    if swaps[n - 1]: a, b, p, q = b, a, q, p
    w(f"{OUT}/t{n}a.wav", a); w(f"{OUT}/t{n}b.wav", b); w(f"{OUT}/t{n}o.wav", ref)
    key[n] = dict(test=kind, clip=c, A=p, B=q, **info)
    trials.append(dict(n=n, voice=desc))
    print(n, key[n], flush=True)
json.dump(dict(trials=trials, key=key), open(f"{OUT}/../key.json", "w"), indent=1)
