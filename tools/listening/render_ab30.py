"""Blind A/B round 30: v3.8 against the ceiling-only v3.9 (sim/hiss_v39.py, cap off), 16 kHz.
Every pair is a band-limited input, where the ceiling fires; a full-band voice gets v3.8's exact
bits, so the one full-band pair is the null (v3.8 against itself).
  LibriSpeech voices low-passed (10th-order Butterworth, zero phase) or cut by their source MP3;
  Kokoro v1.0 TTS phrases (24 kHz, resampled) low-passed or squeezed through 32 kbit/s MP3.
Each output is level-matched to its input; the input is the "Original" player.
Every variant is built fresh in its own worker process with all its flags set (A/B render rule).
Usage: python tools/listening/render_ab30.py CLIPS16_DIR TTS_DIR OUT_AUDIO_DIR   (from the repo root)
TTS_DIR holds tts_<voice>.wav and mp3_<voice>.wav (16 kHz mono; not in the repository)."""
import json, os, random, sys
from multiprocessing import Pool
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt, resample_poly
from pesq import pesq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in ("sim", "", "tools/hiss_proto/ceiling_study"):
    sys.path.insert(0, os.path.join(ROOT, p))
CLIPS, TTS, OUT = sys.argv[1:4]
os.makedirs(OUT, exist_ok=True)
CODES = {"8": "v3.8", "9": "v3.9 ceiling only (no cap)"}
plan = [("9", "LS", "librispeech_251_m", 5000), ("9", "LS", "librispeech_8842_f", 5500),
        ("9", "LS", "librispeech_3536_f", 6000), ("9", "LS", "librispeech_652_m", 4500),
        ("9", "LS", "librispeech_777_m", None), ("9", "LS", "librispeech_3170_m", None),
        ("9", "TTS", "tts_af_heart", 5000), ("9", "TTS", "tts_am_michael", 5500),
        ("9", "TTS", "tts_af_sarah", 4500), ("9", "TTS", "mp3_bf_emma", None),
        ("9", "TTS", "mp3_am_adam", None), ("8", "TTS", "tts_af_nicole", None)]
rng = random.Random(2026112230)
rng.shuffle(plan)
swaps = [True, False] * 6
rng.shuffle(swaps)


def source(src, clip, lp):
    x = sf.read(f"{CLIPS if src == 'LS' else TTS}/{clip}.wav")[0]
    x = x[:len(x) // 320 * 320]
    return sosfiltfilt(butter(10, lp, fs=16000, output="sos"), x) if lp else x


def render(args):
    code, src, clip, lp = args
    import vocoder_lab as vl
    from measure import hb, ENC, DEC
    import hiss_v39 as h9
    vl.TRACK2["lag"] = 8
    x = source(src, clip, lp)
    if code == "8":
        b = hb.SottoV38(**ENC).encode(x)
        y = hb.SottoV38(**DEC).decode_audio16(b, None, n16=len(x))[:len(x)]
        ce = None
    else:
        b = h9.SottoV39(cap=False, ceiling=True, **ENC).encode(x)
        d = h9.SottoV39(cap=False, ceiling=True, **DEC)
        y = d.decode_audio16(b, None, n16=len(x))[:len(x)]
        c = d.frame_ceiling(b)
        g0 = next((g for g, v in enumerate(c) if v is not None), None)
        ce = None if g0 is None else [list(c[g0]), round(g0 * 0.02, 2)]
    return y, ce


def name(src, clip):
    v = clip.split("_", 1)[1]
    if src == "LS":
        return ("Female" if v.endswith("f") else "Male") + f" (LibriSpeech {v.split('_')[0]})"
    return f"Synthesized voice ({v.replace('_', ' ')})"


def cond(src, clip, lp):
    if lp:
        return f"low-passed at {lp / 1000:g} kHz"
    if clip.startswith("mp3_"):
        return "through 32 kbit/s MP3"
    return "source MP3 stops near 7 kHz" if src == "LS" else "full band"


lvl = lambda y, r: y * np.sqrt(np.mean(r ** 2) / (np.mean(y ** 2) + 1e-12))
w = lambda p, y: sf.write(p, np.round(np.clip(y, -1, 1) * 32767).astype(np.int16), 16000, subtype="PCM_16")
wb = lambda x, y: round(float(pesq(16000, x, y[:len(x)], "wb")), 3)

if __name__ == "__main__":
    jobs = sorted({(k, s, c, lp) for p, s, c, lp in plan for k in ("8", p)})
    with Pool(min(len(jobs), os.cpu_count())) as pool:
        got = dict(zip(jobs, pool.map(render, jobs)))
    trials, key = [], {}
    for n, (q, s, c, lp) in enumerate(plan, 1):
        x = source(s, c, lp)
        p = "8"
        (ya, ca), (yb, cb) = got[(p, s, c, lp)], got[(q, s, c, lp)]
        if swaps[n - 1]:
            ya, yb, ca, cb, p, q = yb, ya, cb, ca, q, p
        ya, yb = lvl(ya, x), lvl(yb, x)
        w(f"{OUT}/t{n}o.wav", x); w(f"{OUT}/t{n}a.wav", ya); w(f"{OUT}/t{n}b.wav", yb)
        key[n] = dict(test="null" if p == q else "ab", src=s, clip=c, lowpass=lp, cond=cond(s, c, lp),
                      A=CODES[p], B=CODES[q], ceiling=ca or cb, wb_pesq=[wb(x, ya), wb(x, yb)])
        trials.append(dict(n=n, voice=f"{name(s, c)}, {cond(s, c, lp)}"))
        print(n, key[n], flush=True)
    json.dump(dict(trials=trials, key=key, codes=CODES), open(f"{OUT}/../key.json", "w"), indent=1)
