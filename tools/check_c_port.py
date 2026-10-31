"""Check the C port (c/) against the Python model (sim/vocoder_lab.py SottoV35 with the
fixed-lag tracker, TRACK2["lag"] = 8).

Usage: python tools/check_c_port.py CLIP.flac [...] [--loss 0.1] [--json OUT.json]

Encoder: the fraction of 20 ms frames whose 48 bits match exactly, and which fields differ.
Decoder: both decoders get the same (Python) bits, with a random frame-loss pattern when
--loss is set; reports the sample SNR of the C output against the Python output, plus
PESQ of each against the original so a mismatch can be judged by its effect.
Build c/ first (make -C c).
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
import vocoder_lab as vl                                       # noqa: E402

FIELDS = [("voicing", 0, 2), ("Wo", 2, 9), ("energy", 9, 14), ("vq1", 14, 26), ("vq2", 26, 37),
          ("vq3", 37, 48)]


def c_encode(x16):
    with tempfile.TemporaryDirectory() as d:
        x16.astype("<i2").tofile(f"{d}/in.raw")
        subprocess.run([f"{ROOT}/c/sotto_enc", f"{d}/in.raw", f"{d}/out.bit"], check=True)
        b = np.fromfile(f"{d}/out.bit", np.uint8)
    return np.unpackbits(b).reshape(-1, 48).astype(np.int8)


def c_decode(bits, good=None):
    with tempfile.TemporaryDirectory() as d:
        np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(f"{d}/in.bit")
        args = [f"{ROOT}/c/sotto_dec", f"{d}/in.bit", f"{d}/out.raw"]
        if good is not None:
            np.asarray(good, np.uint8).tofile(f"{d}/good.u8")
            args.append(f"{d}/good.u8")
        subprocess.run(args, check=True)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


def snr_db(ref, y):
    n = min(len(ref), len(y))
    return 10 * np.log10(np.sum(ref[:n] ** 2) / (np.sum((ref[:n] - y[:n]) ** 2) + 1e-20))


def main(clips, loss, out):
    vl.TRACK2["lag"] = 8
    v = vl.SottoV35()
    import audio_race as ar

    def pesq(x, y):
        return ar.score(x, y, ar.CODEC_DELAY)
    rows = []
    for path in clips:
        x, fs = sf.read(path)
        assert fs == 8000
        x = x[:len(x) // 160 * 160]
        x16 = np.round(x * 32767).astype(np.int16)
        xq = x16 / 32767.0
        bp = v.encode(xq)
        bc = c_encode(x16)
        n = min(len(bp), len(bc))
        same = np.all(bp[:n] == bc[:n], 1)
        diff = {name: int(np.sum(np.any(bp[:n, a:b] != bc[:n, a:b], 1))) for name, a, b in FIELDS}
        good = None
        if loss:
            good = np.random.default_rng(1).random(len(bp)) >= loss
            good[0] = True
        yp = vl.synthesise(v.decode(bp, good))
        yc = c_decode(bp, good)
        r = {"clip": os.path.basename(path), "frames": int(n), "frames_py": len(bp), "frames_c": len(bc),
             "bit_exact": round(float(same.mean()), 4), "field_mismatch": diff,
             "dec_snr_db": round(float(snr_db(yp, yc)), 1), "dec_len": [len(yp), len(yc)]}
        if pesq:
            r["pesq_py_dec"] = round(float(pesq(x, yp)[0]), 3)
            r["pesq_c_dec"] = round(float(pesq(x, yc)[0]), 3)
            r["pesq_c_enc_c_dec"] = round(float(pesq(x, c_decode(bc, good))[0]), 3)
        print(json.dumps(r), flush=True)
        rows.append(r)
    if out:
        json.dump(rows, open(out, "w"), indent=1)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("clips", nargs="+")
    a.add_argument("--loss", type=float, default=0.0)
    a.add_argument("--json")
    a = a.parse_args()
    main(a.clips, a.loss, a.json)
