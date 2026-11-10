"""Compare the fixed-point sotto (c/fixed/) with the float C port (c/).

Usage: python tools/check_fx.py CLIP.flac [...] [--loss 0.1] [--json OUT.json]

Decoder: the float encoder's bits go to both decoders (with a random frame-loss pattern when
--loss is set). Reports the sample SNR of the fixed-point output against the float output,
and PESQ of each against the original.
Encoder (--enc): the share of frames whose 48 bits are identical, which fields differ, and
PESQ of float encoder + float decoder, fixed encoder + fixed decoder, and fixed encoder +
float decoder (which isolates the encoder: the float decoder's random phases stay in step
until the bits differ).
v3.8 (--v38, 16 kHz clips): both encoders in their 16 kHz mode (frames identical, fields
that differ: voicing, hiss index, side bit, energy, shape), and the float encoder's bits
through both 16 kHz decoders: the 0-4 kHz sample SNR between them, the full-band SNR (the
hiss band has the same phase sequence in both, so it compares sample for sample too), the
4-8 kHz level difference per 10 ms frame (mean and 95th percentile over frames above
-60 dB), and PESQ-NB of each against the original at 8 kHz.
sotto 1200 (--lr; 8 kHz clips, or 16 kHz clips with --v38 for sotto 1200 hiss): both encoders
in their sotto 1200 mode (superframes identical, fields that differ), then PESQ of the float
decoder on the float encoder's bits and on the fixed encoder's bits, clean and with one
superframe in --every (default 8) lost; and of the fixed decoder on the float encoder's bits
(fxdec) and on the fixed encoder's bits (fxenc_fxdec). At 16 kHz also the 4-8 kHz level
difference per 10 ms between the two decoders on the float bits (mean and 95th percentile).
At 16 kHz PESQ-NB is scored on the output resampled to 8 kHz, and PESQ-WB on the 16 kHz output.
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
FIELDS38 = [("voicing", 0, 2), ("index", 2, 8), ("side", 8, 9), ("energy", 9, 14), ("shape", 14, 48)]


def run_enc(binary, x16, k16=False, lr=False):
    with tempfile.TemporaryDirectory() as d:
        x16.astype("<i2").tofile(f"{d}/in.raw")
        flags = (["-16"] if k16 else []) + (["-1200"] if lr else [])
        subprocess.run([binary] + flags + [f"{d}/in.raw", f"{d}/out.bit"], check=True)
        return np.unpackbits(np.fromfile(f"{d}/out.bit", np.uint8)).reshape(-1, 48).astype(np.int8)


def run_dec(binary, bits, good=None, k16=False, lr=False):
    with tempfile.TemporaryDirectory() as d:
        np.packbits(np.asarray(bits, np.uint8).reshape(-1, 48), axis=1).tofile(f"{d}/in.bit")
        flags = (["-16"] if k16 else []) + (["-1200"] if lr else [])
        args = [binary] + flags + [f"{d}/in.bit", f"{d}/out.raw"]
        if good is not None:
            np.asarray(good, np.uint8).tofile(f"{d}/good.u8")
            args.append(f"{d}/good.u8")
        subprocess.run(args, check=True)
        return np.fromfile(f"{d}/out.raw", "<i2").astype(float) / 32768


def compare_bits(bp, bc, fields):
    n = min(len(bp), len(bc))
    same = np.all(bp[:n] == bc[:n], 1)
    return round(float(same.mean()), 4), {k: int(np.sum(np.any(bp[:n, a:b] != bc[:n, a:b], 1))) for k, a, b in fields}


# sotto 1200's fields (sotto_lr_tables.h); at 16 kHz wa and dw also carry the hiss
FIELDS_LR = [("ca", 0, 2), ("wa", 2, 9), ("ea", 9, 14), ("sa", 14, 32), ("cb", 32, 34), ("dw", 34, 37),
             ("de", 37, 40), ("sb", 40, 48)]


def main_lr(clips, k16, every, seconds, out):
    """sotto 1200 (k16: sotto 1200 hiss): fixed encoder against float encoder, through the
    float decoder (and the fixed decoder on the fixed bits)."""
    import audio_race as ar
    from pesq import pesq
    from scipy.signal import resample_poly
    fs_in = 16000 if k16 else 8000
    fl, fx = f"{ROOT}/c", f"{ROOT}/c/fixed"
    rows = []
    for path in clips:
        x, fs = sf.read(path)
        assert fs == fs_in, f"{path}: {fs} Hz, want {fs_in}"
        if x.ndim > 1:
            x = x[:, 0]
        if seconds:
            x = x[:int(seconds * fs)]
        x = x[:len(x) // (40 * fs // 1000) * (40 * fs // 1000)]
        x16 = np.round(x * 32767).astype(np.int16)
        xq = x16 / 32767.0
        bf = run_enc(f"{fl}/sotto_enc", x16, k16, True)
        bx = run_enc(f"{fx}/sotto_enc_fx", x16, k16, True)
        exact, diff = compare_bits(bf, bx, FIELDS_LR)
        r = {"clip": os.path.basename(path), "superframes": [len(bf), len(bx)], "enc_bit_exact": exact,
             "field_mismatch": diff}
        x8 = resample_poly(xq, 1, 2) if k16 else xq
        for tag, good in (("clean", None), (f"loss1in{every}", np.arange(len(bf)) % every != 3 % every)):
            outs = {"float": run_dec(f"{fl}/sotto_dec", bf, good, k16, True),
                    "fxenc": run_dec(f"{fl}/sotto_dec", bx, good, k16, True)}
            try:
                outs["fxdec"] = run_dec(f"{fx}/sotto_dec_fx", bf, good, k16, True)
                outs["fxenc_fxdec"] = run_dec(f"{fx}/sotto_dec_fx", bx, good[:len(bx)] if good is not None else None,
                                              k16, True)
            except subprocess.CalledProcessError:     # a build without that decoder
                pass
            if k16 and "fxdec" in outs:               # the decoders on the same bits: 4-8 kHz level per 10 ms
                import hiss_band as hb
                yf, yx = outs["float"], outs["fxdec"]
                n = min(len(yf), len(yx))
                hf = hb.bands_db(np.abs(hb.stft(yf[:n])) ** 2, [(4000, 8000)])[:, 0]
                hx = hb.bands_db(np.abs(hb.stft(yx[:n])) ** 2, [(4000, 8000)])[:, 0]
                d = np.abs(hf - hx)[hf > -60]
                if len(d):
                    r[f"dec_hiss_level_diff_db_{tag}"] = [round(float(d.mean()), 2), round(float(np.percentile(d, 95)), 2)]
            for k, y in outs.items():
                y8 = resample_poly(y, 1, 2) if k16 else y
                r[f"pesq_{k}_{tag}"] = round(float(ar.score(x8, y8, ar.CODEC_DELAY)[0]), 3)
                if k16:
                    lag = 2 * ar.CODEC_DELAY
                    n = min(len(xq), len(y) - lag)
                    try:
                        w = pesq(16000, xq[:n], y[lag:lag + n], "wb")
                    except Exception:
                        w = 1.0
                    r[f"pesqwb_{k}_{tag}"] = round(float(w), 3)
        print(json.dumps(r), flush=True)
        rows.append(r)
    if len(rows) > 1:
        fr = sum(r["superframes"][0] for r in rows)
        m = {"superframes": fr, "enc_bit_exact": round(sum(r["enc_bit_exact"] * r["superframes"][0] for r in rows) / fr, 4),
             "field_mismatch": {k: sum(r["field_mismatch"][k] for r in rows) for k, _, _ in FIELDS_LR}}
        m.update({k: round(float(np.mean([r[k] for r in rows])), 3) for k in rows[0] if k.startswith("pesq")})
        m.update({k: [round(float(np.mean([r[k][i] for r in rows])), 2) for i in range(2)]
                  for k in rows[0] if k.startswith("dec_hiss")})
        print("mean", json.dumps(m))
    if out:
        json.dump(rows, open(out, "w"), indent=1)


def main38(clips, loss, seconds, out):
    import audio_race as ar
    import hiss_band as hb
    from scipy.signal import resample_poly
    rows = []
    for path in clips:
        x, fs = sf.read(path)
        assert fs == 16000
        if x.ndim > 1:
            x = x[:, 0]
        if seconds:
            x = x[:int(seconds * fs)]
        x = x[:len(x) // 320 * 320]
        x16 = np.round(x * 32767).astype(np.int16)
        bf = run_enc(f"{ROOT}/c/sotto_enc", x16, True)
        bx = run_enc(f"{ROOT}/c/fixed/sotto_enc_fx", x16, True)
        exact, diff = compare_bits(bf, bx, FIELDS38)
        good = None
        if loss:
            good = np.random.default_rng(1).random(len(bf)) >= loss
            good[0] = True
        yf = run_dec(f"{ROOT}/c/sotto_dec", bf, good, True)
        yx = run_dec(f"{ROOT}/c/fixed/sotto_dec_fx", bf, good, True)
        n = min(len(yf), len(yx))
        lo_f, lo_x = resample_poly(yf[:n], 1, 2), resample_poly(yx[:n], 1, 2)
        hf = hb.bands_db(np.abs(hb.stft(yf[:n])) ** 2, [(4000, 8000)])[:, 0]
        hx = hb.bands_db(np.abs(hb.stft(yx[:n])) ** 2, [(4000, 8000)])[:, 0]
        d = np.abs(hf - hx)[hf > -60]
        # the core's band (random-phase harmonics go out of step, so levels, not samples):
        # 250 Hz bands below 4 kHz per 10 ms frame, frames above -60 dB
        lf = hb.bands_db(np.abs(hb.stft(yf[:n])) ** 2, [(250 * b, 250 * b + 250) for b in range(16)])
        lx = hb.bands_db(np.abs(hb.stft(yx[:n])) ** 2, [(250 * b, 250 * b + 250) for b in range(16)])
        dl = np.abs(lf - lx)[lf > -60]
        x8 = resample_poly(x16 / 32767.0, 1, 2)
        yxx = run_dec(f"{ROOT}/c/fixed/sotto_dec_fx", bx, good, True)
        r = {"clip": os.path.basename(path), "frames": [len(bf), len(bx)],
             "enc_bit_exact": exact, "field_mismatch": diff,
             "dec_low_snr_db": round(float(snr_db(lo_f, lo_x)), 1),
             "dec_full_snr_db": round(float(snr_db(yf[:n], yx[:n])), 1),
             "dec_hiss_level_diff_db": [round(float(d.mean()), 2), round(float(np.percentile(d, 95)), 2)] if len(d) else None,
             "dec_low_band_diff_db": [round(float(dl.mean()), 2), round(float(np.percentile(dl, 95)), 2)] if len(dl) else None,
             "pesq_float": round(float(ar.score(x8, lo_f, ar.CODEC_DELAY)[0]), 3),
             "pesq_fixed_dec": round(float(ar.score(x8, lo_x, ar.CODEC_DELAY)[0]), 3),
             "pesq_fixed": round(float(ar.score(x8, resample_poly(yxx, 1, 2), ar.CODEC_DELAY)[0]), 3)}
        print(json.dumps(r), flush=True)
        rows.append(r)
    if len(rows) > 1:
        fr = sum(r["frames"][0] for r in rows)
        m = {"frames": fr, "enc_bit_exact": round(sum(r["enc_bit_exact"] * r["frames"][0] for r in rows) / fr, 4),
             "field_mismatch": {k: sum(r["field_mismatch"][k] for r in rows) for k, _, _ in FIELDS38}}
        m.update({k: round(float(np.mean([r[k] for r in rows])), 3)
                  for k in ("dec_low_snr_db", "pesq_float", "pesq_fixed_dec", "pesq_fixed")})
        m.update({k: [round(float(np.mean([r[k][i] for r in rows])), 2) for i in range(2)]
                  for k in ("dec_hiss_level_diff_db", "dec_low_band_diff_db")})
        print("mean", json.dumps(m))
    if out:
        json.dump(rows, open(out, "w"), indent=1)


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
    a.add_argument("--v38", action="store_true", help="16 kHz clips through the v3.8 layer (VARIANT=v3.8 builds)")
    a.add_argument("--seconds", type=float, default=0.0, help="--v38, --lr: use the first seconds of each clip")
    a.add_argument("--lr", action="store_true", help="sotto 1200 (with --v38: sotto 1200 hiss, 16 kHz clips)")
    a.add_argument("--every", type=int, default=8, help="--lr: lose one superframe in EVERY")
    a = a.parse_args()
    if a.lr:
        main_lr(a.clips, a.v38, a.every, a.seconds, a.json)
    elif a.v38:
        main38(a.clips, a.loss, a.seconds, a.json)
    else:
        main(a.clips, a.loss, a.json, a.enc)
