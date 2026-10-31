"""Compare the fixed-point sotto (c/fixed/) with the float C port (c/).

Usage: python tools/check_fx.py CLIP.flac [...] [--loss 0.1] [--json OUT.json]

Decoder: the float encoder's bits go to both decoders (with a random frame-loss pattern when
--loss is set). Reports the sample SNR of the fixed-point output against the float output,
and PESQ of each against the original.
Build first: make -C c && make -C c fixed.
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
from check_c_port import c_encode, snr_db          # noqa: E402


def run_dec(binary, bits, good=None):
    with tempfile.TemporaryDirectory() as d:
        np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(f"{d}/in.bit")
        args = [binary, f"{d}/in.bit", f"{d}/out.raw"]
        if good is not None:
            np.asarray(good, np.uint8).tofile(f"{d}/good.u8")
            args.append(f"{d}/good.u8")
        subprocess.run(args, check=True)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


def main(clips, loss, out):
    import audio_race as ar
    rows = []
    for path in clips:
        x, fs = sf.read(path)
        assert fs == 8000
        x = x[:len(x) // 160 * 160]
        bits = c_encode(np.round(x * 32767).astype(np.int16))
        good = None
        if loss:
            good = np.random.default_rng(1).random(len(bits)) >= loss
            good[0] = True
        yf = run_dec(f"{ROOT}/c/sotto_dec", bits, good)
        yx = run_dec(f"{ROOT}/c/fixed/sotto_dec_fx", bits, good)
        r = {"clip": os.path.basename(path), "frames": len(bits),
             "dec_snr_db": round(float(snr_db(yf, yx)), 1),
             "pesq_float": round(float(ar.score(x, yf, ar.CODEC_DELAY)[0]), 3),
             "pesq_fixed": round(float(ar.score(x, yx, ar.CODEC_DELAY)[0]), 3)}
        print(json.dumps(r), flush=True)
        rows.append(r)
    if len(rows) > 1:
        m = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in ("dec_snr_db", "pesq_float", "pesq_fixed")}
        m["min_dec_snr_db"] = min(r["dec_snr_db"] for r in rows)
        print("mean", json.dumps(m))
    if out:
        json.dump(rows, open(out, "w"), indent=1)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("clips", nargs="+")
    a.add_argument("--loss", type=float, default=0.0)
    a.add_argument("--json")
    a = a.parse_args()
    main(a.clips, a.loss, a.json)
