"""8-12 s "zero ... nine" test clips from Speech Commands v0.02 (CC BY 4.0, Warden 2018).

Usage: python tools/sc_counting_clips.py SC_DIR OUT_DIR
"""
import os, sys, json, numpy as np, soundfile as sf, librosa
D = sys.argv[1]; OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)
WORDS = ["testing"] if os.path.isdir(f"{D}/testing") else []
WORDS += ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
spk = None
for w in WORDS:
    s = {f.split("_")[0] for f in os.listdir(f"{D}/{w}") if f.endswith("_nohash_0.wav")}
    spk = s if spk is None else spk & s
print(len(spk), "speakers with all words", WORDS[:1], flush=True)
def trim(x, fs):
    f = 160; n = len(x) // f
    e = 10 * np.log10((x[:n * f].reshape(n, f) ** 2).mean(1) + 1e-10)
    floor = np.percentile(e, 10); on = np.where(e > floor + 15)[0]
    if len(on) == 0: return None, 0, 0
    a, b = max(0, on[0] - 4) * f, min(n, on[-1] + 5) * f
    return x[a:b], e.max() - floor, np.abs(x).max()
rows = []
for s in sorted(spk):
    parts, snrs, ok = [], [], True
    for w in WORDS:
        x, fs = sf.read(f"{D}/{w}/{s}_nohash_0.wav")
        y, snr, pk = trim(x, fs)
        if y is None or pk > 0.98 or len(y) < 0.2 * fs: ok = False; break
        parts.append(y); snrs.append(snr)
    if not ok: continue
    gap = np.zeros(int(0.25 * fs))
    seq = [parts[0], np.zeros(int(0.5 * fs))] if WORDS[0] == "testing" else []
    for p in parts[len(seq) // 2 if seq else 0:]:
        seq += [p, gap]
    x = np.concatenate(seq)
    x8 = librosa.resample(x, orig_sr=fs, target_sr=8000)
    f0, vf, _ = librosa.pyin(x8, fmin=60, fmax=450, sr=8000, frame_length=1024, hop_length=80)
    rows.append(dict(spk=s, snr=float(np.min(snrs)), f0=float(np.nanmedian(f0[vf])) if vf.any() else 0, dur=len(x8) / 8000, x8=x8))
print(len(rows), "usable", flush=True)
rows.sort(key=lambda r: -r["snr"])
low = [r for r in rows if 0 < r["f0"] < 145][:6]; high = [r for r in rows if r["f0"] > 175][:6]
meta = []
for tag, grp in (("lower", low), ("higher", high)):
    for i, r in enumerate(grp, 1):
        x = r["x8"] / np.abs(r["x8"]).max() * 0.7
        name = f"sc_{tag}{i}_{r['spk']}"
        sf.write(f"{OUT}/{name}.flac", x, 8000, subtype="PCM_16")
        meta.append(dict(name=name, speaker=r["spk"], snr_db=round(r["snr"], 1), median_f0=round(r["f0"]), seconds=round(r["dur"], 1)))
        print(meta[-1], flush=True)
json.dump(meta, open(f"{OUT}/clips.json", "w"), indent=1)
