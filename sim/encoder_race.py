"""Encoder against encoder: Codec 2 2400 and the sotto encoders, each sent through the same
sotto VW payload, C4FM softmodem, FM channel (same fading seeds) and receiver.

Usage: python sim/encoder_race.py [--samples DIR] [--out FILE] [--render DIR] [--codecs a,b]
"""
import argparse, json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import audio_race as ar
import vocoder_lab as vl
import waveforms as wf
import c4fm_sim as cs
from audio_io import write_flac
from modem.link import Transmitter, Receiver, CODEC2_2400_MUTE

CONDS = [dict(name="No radio channel", cn0=None, fd=0.0),
         dict(name="446 MHz 60 km/h 52 dB-Hz", cn0=52, fd=cs.doppler(446e6, 60)),
         dict(name="446 MHz 60 km/h 56 dB-Hz", cn0=56, fd=cs.doppler(446e6, 60)),
         dict(name="146 MHz 30 km/h 56 dB-Hz", cn0=56, fd=cs.doppler(146e6, 30))]


def tag(s):
    return s.replace(" ", "_").replace("/", "")


def make_codecs(names):
    mute = np.zeros(48, np.int8)                 # unvoiced, lowest Wo, energy 0 dB, flat shape
    out = {}
    for name in names:
        if name == "codec2_2400":
            out[name] = dict(enc=lambda x: ar.c2enc(np.round(x * 32767)), dec=lambda b, g: ar.c2dec(b),
                             mute=CODEC2_2400_MUTE)
        elif name == "sotto_v0":
            v = vl.SottoV0()
            out[name] = dict(enc=v.encode, dec=lambda b, g, v=v: v.decode_audio(b), mute=mute)
        elif name == "sotto_v1":
            v = vl.SottoV0(pitch="tracked")
            out[name] = dict(enc=v.encode, dec=lambda b, g, v=v: v.decode_audio(b), mute=mute)
        elif name == "sotto_v2":
            v = vl.SottoV2()
            out[name] = dict(enc=v.encode, dec=lambda b, g, v=v: v.decode_audio(b), mute=mute)
        elif name == "sotto_v3":
            v = vl.SottoV3()
            out[name] = dict(enc=v.encode, dec=lambda b, g, v=v: v.decode_audio(b), mute=mute)
        elif name.startswith("sotto_v2p"):            # sotto_v2p<N>, N = forced reset period (0 = none)
            v = vl.SottoV2P(every=int(name[9:] or 0) or None)
            out[name] = dict(enc=v.encode, dec=lambda b, g, v=v: vl.synthesise(v.decode(b, g)), mute=mute)
        elif name == "sotto_v1_pred":
            v = vl.SottoV1(shrink=1.0)
            out[name] = dict(enc=v.encode, dec=lambda b, g, v=v: vl.synthesise(v.decode(b, g)), mute=mute)
    return out


def main(samples, render=None, seeds=(1, 2, 3), names=("codec2_2400", "sotto_v0")):
    codecs = make_codecs(names)
    clips = ar.load_clips(samples)
    res = []
    for cond in CONDS:
        for cname, cd in codecs.items():
            t = time.time()
            per = {}
            for c, x in clips.items():
                bits = cd["enc"](x)
                n = len(bits)
                scores = []
                for sd in (seeds if cond["cn0"] else seeds[:1]):
                    if cond["cn0"] is None:
                        fr, good = bits, np.ones(n, bool)
                    else:
                        tx = Transmitter("sotto_vw").modulate(bits)
                        disc, _ = wf.fm_channel(tx, cond["cn0"], fd=cond["fd"], seed=sd * 100 + len(c))
                        rx = Receiver("sotto_vw", mute=cd["mute"]).receive(disc, t0=ar.LEAD + 4800)
                        fr = rx["frames"]
                        fr = np.concatenate([fr, np.repeat(cd["mute"][None], max(0, n - len(fr)), 0)])[:n]
                        good = np.concatenate([rx["good"], np.zeros(max(0, n - len(rx["good"])), bool)])[:n]
                    y = cd["dec"](fr, good)
                    scores.append(ar.score(x, y, ar.best_lag(x, y)))
                    if render and sd == seeds[0]:
                        write_flac(os.path.join(render, f"{c}__{tag(cond['name'])}__{cname}.flac"), y, 8000)
                per[c] = dict(pesq=float(np.mean([s[0] for s in scores])),
                              estoi=float(np.mean([s[1] for s in scores])))
            res.append(dict(cond=cond["name"], codec=cname, per_clip=per))
            print(json.dumps(dict(cond=cond["name"], codec=cname, sec=round(time.time() - t, 1),
                                  pesq={c: round(v["pesq"], 2) for c, v in per.items()})), flush=True)
    return res


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--samples", default=ar.SAMPLES)
    a.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "docs", "results", "encoder_race.json"))
    a.add_argument("--render")
    a.add_argument("--codecs", default="codec2_2400,sotto_v0")
    a = a.parse_args()
    if a.render:
        os.makedirs(a.render, exist_ok=True)
    r = main(a.samples, a.render, names=a.codecs.split(","))
    with open(a.out, "w") as f:
        json.dump(r, f, indent=1)
