"""Depth-1 (100 ms) vs depth-2 (200 ms) interleaving for the sotto VW payload on 2 m fading,
decoded with sotto v3.5. Usage: python tools/interleave_race.py CLIP.flac [...] --out FILE.json"""
import argparse, json, os, sys
import numpy as np, soundfile as sf
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))
sys.path.insert(0, os.path.dirname(HERE))
import audio_race as ar, vocoder_lab as vl, waveforms as wf, c4fm_sim as cs   # noqa: E402
from modem.link import Transmitter, Receiver                                  # noqa: E402
from modem.interleave import Transmitter2, Receiver2                          # noqa: E402

CONDS = [(kmh, cn0) for kmh in (5, 30, 60, 100) for cn0 in (52, 56)]


def run(bits, tx_cls, rx_cls, kmh, cn0, seed):
    n = len(bits)
    tx = tx_cls("sotto_vw").modulate(bits)
    disc, _ = wf.fm_channel(tx, cn0, fd=cs.doppler(146e6, kmh), seed=seed)
    rx = rx_cls("sotto_vw", mute=np.zeros(48, np.int8)).receive(disc, t0=ar.LEAD + 4800)
    fr = np.concatenate([rx["frames"], np.zeros((max(0, n - len(rx["frames"])), 48), np.int8)])[:n]
    good = np.concatenate([rx["good"], np.zeros(max(0, n - len(rx["good"])), bool)])[:n]
    return fr, good


def main(clips, out, seeds=(1, 2, 3)):
    v = vl.SottoV35()
    res = {}
    for kmh, cn0 in CONDS:
        key = f"146MHz_{kmh}kmh_{cn0}dBHz"
        acc = {}
        for c in clips:
            x = sf.read(c)[0]
            bits = v.encode(x)
            for sd in seeds:
                for name, t, r in (("depth1", Transmitter, Receiver), ("depth2", Transmitter2, Receiver2)):
                    fr, good = run(bits, t, r, kmh, cn0, sd * 100 + len(c))
                    y = vl.synthesise(v.decode(fr, good))
                    acc.setdefault(name, []).append(ar.score(x, y, ar.CODEC_DELAY)[0])
                    acc.setdefault(name + "_loss", []).append(1 - good.mean())
        res[key] = {k: float(np.mean(a)) for k, a in acc.items()}
        print(key, {k: round(a, 3) for k, a in res[key].items()}, flush=True)
    json.dump(res, open(out, "w"), indent=1)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("clips", nargs="+")
    a.add_argument("--out", required=True)
    a = a.parse_args()
    main(a.clips, a.out)
