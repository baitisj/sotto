"""Compare the fixed-point sotto (c/fixed/) with the float C port (c/).

Usage: python tools/check_fx.py CLIP.flac [...] [--loss 0.1] [--json OUT.json]

Decoder: the float encoder's bits go to both decoders (with a random frame-loss pattern when
--loss is set). Reports the sample SNR of the fixed-point output against the float output,
and PESQ of each against the original.
Encoder (--enc): the share of frames whose 48 bits are identical, which fields differ, and
PESQ of float encoder + float decoder, fixed encoder + fixed decoder, and fixed encoder +
float decoder (which isolates the encoder: the float decoder's random phases stay in step
until the bits differ).
Build first: make -C c && make -C c fixed.
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
from check_c_port import c_encode, snr_db          # noqa: E402

FIELDS = [("voicing", 0, 2), ("Wo", 2, 9), ("energy", 9, 14), ("vq", 14, 48)]


def run_enc(binary, x16):
    with tempfile.TemporaryDirectory() as d:
        x16.astype("<i2").tofile(f"{d}/in.raw")
        subprocess.run([binary, f"{d}/in.raw", f"{d}/out.bit"], check=True)
        return np.unpackbits(np.fromfile(f"{d}/out.bit", np.uint8)).reshape(-1, 48).astype(np.int8)


def run_dec(binary, bits, good=None):
    with tempfile.TemporaryDirectory() as d:
        np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(f"{d}/in.bit")
        args = [binary, f"{d}/in.bit", f"{d}/out.raw"]
        if good is not None:
            np.asarray(good, np.uint8).tofile(f"{d}/good.u8")
            args.append(f"{d}/good.u8")
        subprocess.run(args, check=True)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


def main(clips, loss, out, enc=False):
    import audio_race as ar
    rows = []
    for path in clips:
        x, fs = sf.read(path)
        assert fs == 8000
        x = x[:len(x) // 160 * 160]
        x16 = np.round(x * 32767).astype(np.int16)
        bits = c_encode(x16)
        if enc:
            bx = run_enc(f"{ROOT}/c/fixed/sotto_enc_fx", x16)
            n = min(len(bits), len(bx))
            same = np.all(bits[:n] == bx[:n], 1)
            r = {"clip": os.path.basename(path), "frames": int(n), "frames_fx": len(bx),
                 "bit_exact": round(float(same.mean()), 4),
                 "field_mismatch": {k: int(np.sum(np.any(bits[:n, a:b] != bx[:n, a:b], 1))) for k, a, b in FIELDS},
                 "pesq_float": round(float(ar.score(x, run_dec(f"{ROOT}/c/sotto_dec", bits), ar.CODEC_DELAY)[0]), 3),
                 "pesq_fixed": round(float(ar.score(x, run_dec(f"{ROOT}/c/fixed/sotto_dec_fx", bx), ar.CODEC_DELAY)[0]), 3),
                 "pesq_fxenc_floatdec": round(float(ar.score(x, run_dec(f"{ROOT}/c/sotto_dec", bx), ar.CODEC_DELAY)[0]), 3)}
            print(json.dumps(r), flush=True)
            rows.append(r)
            continue
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
    if len(rows) > 1 and enc:
        fr = sum(r["frames"] for r in rows)
        m = {"frames": fr, "bit_exact": round(sum(r["bit_exact"] * r["frames"] for r in rows) / fr, 4),
             "field_mismatch": {k: sum(r["field_mismatch"][k] for r in rows) for k, _, _ in FIELDS}}
        m.update({k: round(float(np.mean([r[k] for r in rows])), 3)
                  for k in ("pesq_float", "pesq_fixed", "pesq_fxenc_floatdec")})
        print("mean", json.dumps(m))
    elif len(rows) > 1:
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
    a.add_argument("--enc", action="store_true", help="compare the encoders")
    a = a.parse_args()
    main(a.clips, a.loss, a.json, a.enc)
