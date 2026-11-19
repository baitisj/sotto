"""Golden outputs: fail when a change moves what the release-candidate modes produce.

A cleanup (a refactor, a table rewrite, a compiler flag) should leave every bit and sample
alone; PR #13's lesson was to compare outputs after one. This makes that automatic. For two
voices (6 s of each) and every mode in MODES, tests/golden/ holds:

  - the encoder's frames (tests/golden/<voice>__<mode>.bit), compared frame by frame;
  - each float decoder's PESQ-NB on those frames, clean and with every 13th frame lost
    (float output differs in the last bits between compilers, targets and libms, so it is
    compared by score, to within PESQ_TOL; the frames and the fixed-point hashes are the
    exact checks);
  - a SHA-256 of each fixed-point (integer-only) decoder's samples on those frames, clean and
    with losses: they must match exactly on any machine (their PESQ-NB is kept beside it, so
    a moved hash comes with what it did to the score).

Decoders always decode the stored frames, so an encoder change and a decoder change show up
separately. tests/test_golden.py runs the check in `make check` and CI.

Usage:
  python tools/golden.py            check; exit 1 and list what moved
  python tools/golden.py --update   rewrite tests/golden/ (then commit it, and say in the PR
                                    why the output changed and what PESQ did)
Build first: make, make fixed and make c37 (the plain modes run on the v3.7 copy).
SPDX-License-Identifier: MIT
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf
from pesq import pesq
from scipy.signal import resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "tests", "golden")
C38 = os.path.join(ROOT, "c")                     # the default build, VARIANT=v3.8
C37 = os.path.join(ROOT, "build", "c37")          # make c37: the v3.7 core the K6 plays
SECONDS = 6                                       # a whole number of 120 ms (sotto 400) frames
LOSS_EVERY = 13
PESQ_TOL = 0.02                                   # GCC 15 x86-64-v3 moved one by 0.005

# 16 kHz voices from docs/samples/v38/, with their 8 kHz versions from docs/samples/ for the
# plain modes (read as stored, so no resampler sits between the files and the encoders)
VOICES = [
    "female_libri198_14s",
    "male_libri3436_15s",
]

# name: (input rate, build, encoder flags, float decoder [exe, flags], fixed decoders {label: [exe, flags]})
# v3.8 hiss modes are what the page and the UV-380 play; plain modes are the K6's 8 kHz codecs.
MODES = {
    "2400": (16000, C38, ["-16"],
             ["sotto_dec", "-16"],
             {"fx": ["fixed/sotto_dec_fx", "-16"],
              "fx_k6": ["fixed/sotto_dec_fx_k6", "-16"]}),
    "1200": (16000, C38, ["-16", "-1200"],
             ["sotto_dec", "-16", "-1200"],
             {"fx": ["fixed/sotto_dec_fx", "-16", "-1200"],
              "fx_k6": ["fixed/sotto_dec_fx_k6", "-16", "-1200"]}),
    "600": (16000, C38, ["-16", "-600"],
            ["sotto_dec", "-16", "-600"],
            {"fx_k6": ["fixed/sotto_dec_fx_k6", "-16", "-600"]}),
    "400": (16000, C38, ["-16", "-400"],
            ["sotto_dec", "-16", "-400"],
            {"fx_k6": ["fixed/sotto_dec_fx_k6", "-16", "-400"]}),
    "plain2400": (8000, C37, [],
                  ["sotto_dec"],
                  {"fx": ["fixed/sotto_dec_fx"],
                   "fx_m0": ["fixed/sotto_dec_fx_m0"]}),
    "plain1200": (8000, C37, ["-1200"],
                  ["sotto_dec", "-1200"],
                  {"fx": ["fixed/sotto_dec_fx", "-1200"],
                   "fx_m0": ["fixed/sotto_dec_fx_m0", "-1200"]}),
    "plain600": (8000, C37, ["-600"],
                 None,
                 {"fx_vlr": ["fixed/sotto_vlr_dec_fx", "600"]}),
    "plain400": (8000, C37, ["-400"],
                 None,
                 {"fx_vlr": ["fixed/sotto_vlr_dec_fx", "400"]}),
}


def need_builds():
    """The binaries this needs that are missing."""
    exes = set()
    for _, cdir, _, fdec, fixed in MODES.values():
        exes.add(os.path.join(cdir, "sotto_enc"))
        if fdec:
            exes.add(os.path.join(cdir, fdec[0]))
        exes.update(os.path.join(cdir, f[0]) for f in fixed.values())
    return sorted(e for e in exes if not os.path.exists(e))


def load(voice, fs):
    path = (f"{ROOT}/docs/samples/v38/{voice}__original16.flac" if fs == 16000
            else f"{ROOT}/docs/samples/{voice}__original.flac")
    x, r = sf.read(path, dtype="int16")
    assert r == fs, path
    return x[:SECONDS * fs]


def encode(cdir, flags, x, d):
    x.astype("<i2").tofile(f"{d}/in.raw")
    subprocess.run([f"{cdir}/sotto_enc", *flags, f"{d}/in.raw", f"{d}/out.bit"], check=True)
    return open(f"{d}/out.bit", "rb").read()


def decode(cdir, cmd, bits, good, d):
    open(f"{d}/dec.bit", "wb").write(bits)
    args = [f"{cdir}/{cmd[0]}", *cmd[1:], f"{d}/dec.bit", f"{d}/dec.raw"]
    if good is not None:
        np.asarray(good, np.uint8).tofile(f"{d}/good.u8")
        args.append(f"{d}/good.u8")
    subprocess.run(args, check=True)
    return open(f"{d}/dec.raw", "rb").read()


def loss_mask(bits):
    good = np.arange(len(bits) // 6) % LOSS_EVERY != LOSS_EVERY - 1
    good[0] = True
    return good


def pesq_nb(ref8, raw, fs):
    y = np.frombuffer(raw, "<i2").astype(float) / 32768
    if fs == 16000:
        y = resample_poly(y, 1, 2)
    n = min(len(ref8), len(y))
    return round(float(pesq(8000, ref8[:n], y[:n], "nb")), 3)


def measure(voice, mode, bits, d):
    """Scores and hashes of the decoders on these frames."""
    fs, cdir, _, fdec, fixed = MODES[mode]
    ref8 = load(voice, 8000) / 32768
    out = {"frames": len(bits) // 6}
    for tag, good in (("", None), ("_loss", loss_mask(bits))):
        if fdec:
            out["pesq_nb" + tag] = pesq_nb(ref8, decode(cdir, fdec, bits, good, d), fs)
        for label, cmd in fixed.items():
            raw = decode(cdir, cmd, bits, good, d)
            out[f"sha256_{label}{tag}"] = hashlib.sha256(raw).hexdigest()[:16]
            out[f"pesq_nb_{label}{tag}"] = pesq_nb(ref8, raw, fs)     # says what a moved hash did
    return out


def run(update):
    missing = need_builds()
    if missing:
        sys.exit("golden: missing " + ", ".join(os.path.relpath(m, ROOT) for m in missing)
                 + " (make, make fixed, make c37)")
    path = os.path.join(GOLDEN, "golden.json")
    want = {} if update else json.load(open(path))["outputs"]
    got, problems = {}, []
    os.makedirs(GOLDEN, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        for voice in VOICES:
            for mode, (fs, cdir, eflags, _, _) in MODES.items():
                key = f"{voice}__{mode}"
                bfile = os.path.join(GOLDEN, f"{key}.bit")
                bits = encode(cdir, eflags, load(voice, fs), d)
                if update:
                    open(bfile, "wb").write(bits)
                else:
                    gold = open(bfile, "rb").read()
                    if bits != gold:
                        a = np.frombuffer(bits, np.uint8)
                        b = np.frombuffer(gold, np.uint8)
                        if len(a) != len(b):
                            problems.append(f"{key}: encoder wrote {len(a) // 6} frames, golden has {len(b) // 6}")
                        else:
                            nd = int(np.any((a != b).reshape(-1, 6), 1).sum())
                            problems.append(f"{key}: encoder frames differ in {nd} of {len(a) // 6}")
                    bits = gold                       # decoders always decode the golden frames
                got[key] = m = measure(voice, mode, bits, d)
                for k, v in m.items():
                    w = want.get(key, {}).get(k) if not update else v
                    if w is None:
                        problems.append(f"{key}: {k} not in golden.json")
                    elif k.startswith("pesq"):
                        if abs(v - w) > PESQ_TOL:
                            problems.append(f"{key}: {k} {v:.3f}, golden {w:.3f} ({v - w:+.3f})")
                    elif v != w:
                        problems.append(f"{key}: {k} {v}, golden {w}")
                print(key, json.dumps(m), flush=True)
    if update:
        with open(path, "w") as f:
            json.dump({"note": "tools/golden.py --update writes this; see its docstring", "seconds": SECONDS,
                       "loss_every": LOSS_EVERY, "outputs": got}, f, indent=1, sort_keys=False)
            f.write("\n")
        print(f"wrote {os.path.relpath(GOLDEN, ROOT)}/")
        return 0
    if problems:
        print("\nGOLDEN OUTPUTS MOVED:\n  " + "\n  ".join(problems))
        print("\nIf the change was meant to change the output, run python tools/golden.py --update, "
              "commit tests/golden/, and say in the PR why and what PESQ did.")
        return 1
    print("golden outputs unchanged")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="rewrite tests/golden/")
    a = ap.parse_args()
    sys.exit(run(a.update))
