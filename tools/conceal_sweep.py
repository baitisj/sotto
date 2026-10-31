"""Concealment sweep on 2 m fading: Codec 2 and v3.3 with the receiver's repeat-3-then-mute,
v3.4 decoder concealment variants. Channel runs shared across codecs per (cond, clip, seed)."""
import sys, os, json, glob, numpy as np, soundfile as sf
sys.path.insert(0, "sim"); sys.path.insert(0, ".")
import audio_race as ar, vocoder_lab as vl, waveforms as wf, c4fm_sim as cs
from modem.link import Transmitter, Receiver, CODEC2_2400_MUTE
S = os.environ.get("SOTTO_SCRATCH", "scratch")   # holds pub3/ and test16/ clips, gets conceal/r/
clips = {os.path.basename(f)[:-5]: sf.read(f)[0] for f in
         [f"{S}/pub3/female_libri198_14s.flac", f"{S}/pub3/male_libri3436_15s.flac", f"{S}/pub3/male_ve9qrp_15s.flac",
          f"{S}/test16/librispeech_3536_f.flac", f"{S}/test16/librispeech_251_m.flac",
          f"{S}/test16/ears_p047_f.flac", f"{S}/test16/ears_p107_m.flac"]}
conds = [(kmh, cn0) for kmh in (5, 30, 60) for cn0 in (52, 56)]
v33 = vl.SottoV33()
variants = {"v34_s3_m2_l8": vl.SottoV34(slope=3, mix_after=2, max_lost=8),
            "v34_s6_m2_l8": vl.SottoV34(slope=6, mix_after=2, max_lost=8),
            "v34_s3_m99_l8": vl.SottoV34(slope=3, mix_after=99, max_lost=8),
            "v34_s3_m2_l4": vl.SottoV34(slope=3, mix_after=2, max_lost=4),
            "v34_s2_m2_l15": vl.SottoV34(slope=2, mix_after=2, max_lost=15)}
mute = np.zeros(48, np.int8)
res = {}
for kmh, cn0 in conds:
    key = f"146MHz_{kmh}kmh_{cn0}dBHz"; res[key] = {}
    for c, x in clips.items():
        b2 = ar.c2enc(np.round(x * 32767)); bs = v33.encode(x)
        sc = {}
        for sd in (1, 2, 3):
            for name, bits, mu in (("codec2", b2, CODEC2_2400_MUTE), ("sotto", bs, mute)):
                n = len(bits)
                tx = Transmitter("sotto_vw").modulate(bits)
                disc, _ = wf.fm_channel(tx, cn0, fd=cs.doppler(146e6, kmh), seed=sd * 100 + len(c))
                rx = Receiver("sotto_vw", mute=mu).receive(disc, t0=ar.LEAD + 4800)
                fr = np.concatenate([rx["frames"], np.repeat(mu[None], max(0, n - len(rx["frames"])), 0)])[:n]
                good = np.concatenate([rx["good"], np.zeros(max(0, n - len(rx["good"])), bool)])[:n]
                if name == "codec2":
                    outs = {"codec2": ar.c2dec(fr)}
                else:
                    outs = {"v33": v33.decode_audio(fr)}
                    for k, v in variants.items():
                        outs[k] = vl.synthesise(v.decode(fr, good))
                for k, y in outs.items():
                    sc.setdefault(k, []).append(ar.score(x, y, ar.CODEC_DELAY)[0])
                    if sd == 1 and k in ("codec2", "v33", "v34_s3_m2_l8"):
                        sf.write(f"{S}/conceal/r/{c}__{key}__{k}.wav", y, 8000)
                if name == "sotto": sc.setdefault("frame_loss", []).append(1 - good.mean())
        res[key][c] = {k: float(np.mean(v)) for k, v in sc.items()}
        print(key, c, {k: round(v, 2) for k, v in res[key][c].items()}, flush=True)
    json.dump(res, open(f"{S}/conceal/sweep.json", "w"), indent=1)
ks = list(next(iter(next(iter(res.values())).values())).keys())
for key in res:
    print(key, {k: round(np.mean([r[k] for r in res[key].values()]), 3) for k in ks})
print("ALL", {k: round(np.mean([r[k] for d in res.values() for r in d.values()]), 3) for k in ks})
