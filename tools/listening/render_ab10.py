"""Blind A/B round 10: sotto v3.5 against v3.6 (9+9+8+8 codebook in 8-bit values, energy
field measured on the 200-3700 Hz envelope), no radio channel, 80 ms real-time tracker.
Includes round 9's pair 5 voice (EARS p020, whose opening hum v3.5 turned into a buzz) and
the voice where PESQ dropped (EARS p047). Original in every pair; one identical null pair.
Usage: python tools/listening/render_ab10.py OUT_AUDIO_DIR  (from the repository root)"""
import sys, json, random, numpy as np, soundfile as sf
sys.path.insert(0, "sim")
import audio_race as ar, vocoder_lab as vl
OUT = sys.argv[1]
CL = "/mnt/project-files/vocoder/samples-clean"
SRC = {"male_ve9qrp_15s": "/mnt/project-files/vocoder/samples15/male_ve9qrp_15s.flac",
       "female_libri198_14s": "/mnt/project-files/vocoder/samples15/female_libri198_14s.flac"}
for n in ("ears_p020_m", "ears_p047_f", "ears_p107_m", "ears_p070_f", "librispeech_777_m",
          "librispeech_8842_f", "librispeech_652_m", "librispeech_3081_f"):
    SRC[n] = f"{CL}/{n}.flac"
def name(c):
    if c.startswith("ears"):
        return ("Female" if c.endswith("f") else "Male") + " (EARS studio)"
    if "ve9qrp" in c:
        return "Male (VE9QRP)"
    sp = c.split("_")[1].replace("libri", "")
    return ("Female" if c.startswith("female") or c.endswith("_f") else "Male") + f" (LibriSpeech {sp})"
plan = [("ab", c) for c in ("ears_p020_m", "ears_p047_f", "ears_p107_m", "ears_p070_f", "librispeech_777_m",
                            "librispeech_8842_f", "librispeech_652_m", "male_ve9qrp_15s", "librispeech_3081_f",
                            "female_libri198_14s")] + [("null", "ears_p020_m")]
rng = random.Random(2026103110); rng.shuffle(plan)
swaps = [True, False] * 6; rng.shuffle(swaps)
vl.TRACK2["lag"] = 8
V = {"v35": vl.SottoV35(), "v36": vl.SottoV36()}
def cut(y, s=10):
    y = y[:int(s * 8000)].copy(); f = 160
    y[:f] *= np.linspace(0, 1, f); y[-f:] *= np.linspace(1, 0, f); return y
lvl = lambda y, r: y * np.sqrt(np.mean(r ** 2) / (np.mean(y ** 2) + 1e-12))
w = lambda p, y: sf.write(p, np.round(np.clip(y, -1, 1) * 32767).astype(np.int16), 8000, subtype="PCM_16")
trials, key, cache = [], {}, {}
for n, (kind, c) in enumerate(plan, 1):
    x = sf.read(SRC[c])[0]; x = x[:len(x) // 160 * 160]; ref = cut(x)
    for k, v in V.items():
        if (c, k) not in cache:
            y = vl.synthesise(v.decode(v.encode(x)))
            cache[c, k] = (y[ar.CODEC_DELAY:], round(float(ar.score(x, y, ar.CODEC_DELAY)[0]), 2))
    p, q = ("v36", "v36") if kind == "null" else ("v35", "v36")
    (ya, sa), (yb, sb) = cache[c, p], cache[c, q]
    a, b = lvl(cut(ya), ref), lvl(cut(yb), ref)
    if swaps[n - 1]: a, b, p, q, sa, sb = b, a, q, p, sb, sa
    w(f"{OUT}/t{n}a.wav", a); w(f"{OUT}/t{n}b.wav", b); w(f"{OUT}/t{n}o.wav", ref)
    key[n] = dict(test=kind, clip=c, A=p, B=q, pesq_A=sa, pesq_B=sb)
    trials.append(dict(n=n, voice=f"{name(c)}, no radio channel"))
    print(n, key[n], flush=True)
json.dump(dict(trials=trials, key=key), open(f"{OUT}/../key.json", "w"), indent=1)
