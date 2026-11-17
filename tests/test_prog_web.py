"""The progressive demo page (docs/progressive.html): its delivery orders (docs/sotto-prog.js)
against sim/sotto_prog.py, and the WebAssembly partial decoder (sotto_wasm_decode16_prog in
docs/sotto.wasm) against the Python fill rules and the streamed decoder."""
import json, os, shutil, subprocess, sys
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="needs node")
FIELDS = ["c", "w", "e", "s0", "s1", "s2", "s3"]


def js(code):
    r = subprocess.run([NODE, "--input-type=module", "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
@pytest.mark.parametrize("ns", [1, 2, 3, 5, 17, 160, 600, 601])
def test_orders_match_python(ns):
    import sotto_prog as sp
    sc = sp.SCRIPTS["2400"]["SI"]
    got = js(f"""
import * as P from "./docs/sotto-prog.js";
const f = o => o.items.map(it => [it.sf, it.f]);
console.log(JSON.stringify({{ prog: f(P.progressiveOrder({ns})), ends: P.progressiveOrder({ns}).ends,
  jit165: f(P.jitOrder({ns}, 1.65)), jit085: f(P.jitOrder({ns}, 0.85)), jit124: f(P.jitOrder({ns}, 1.24)) }}));
""")
    idx = {k: i for i, k in enumerate(FIELDS)}
    seq, ends = sp.order("2400", ns, sc)
    assert got["prog"] == [[s, idx[k]] for s, k in seq]
    assert got["ends"] == ends
    for key, ratio in [("jit165", 1.65), ("jit085", 0.85), ("jit124", 1.24)]:
        assert got[key] == [[s, idx[k]] for s, k in sp.jit_order("2400", ns, sc, 1, ratio)]


@needs_node
def test_wasm_partial_decoder():
    """Every field known: the partial decoder gives decode16's samples exactly. Partial masks
    (scans, random): it runs and gives audio of the right length."""
    got = js("""
import { loadSotto } from "./docs/sotto.js";
import fs from "fs";
const s = await loadSotto(fs.readFileSync("docs/sotto.wasm"));
const fr = new Uint8Array(fs.readFileSync("docs/samples/rates/librispeech_251_m__2400.bit"));
const n = fr.length / 6, k = new Uint8Array(n).fill(0x7f);
const full = s.decode16(fr), p = s.decode16Prog(fr, k);
let same = full.length === p.length; for (let i = 0; same && i < p.length; i++) same = full[i] === p[i];
k.forEach((_, i) => k[i] = i % 2 ? 0 : 0x0f);
const q = s.decode16Prog(fr, k);
let e = 0; for (const v of q) e += v * v;
console.log(JSON.stringify({ same, n, len: q.length, rms: Math.sqrt(e / q.length) }));
""")
    assert got["same"]
    assert got["len"] == got["n"] * 320
    assert got["rms"] > 100


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "c", "libsotto.a")), reason="needs the C build (make)")
def test_c_fill_matches_python(tmp_path):
    """sotto_prog_fill2400 (C) gives the frame fields sim/sotto_prog.partial_frames gives."""
    import sotto_prog as sp, vocoder_lab as vl
    exe = tmp_path / "fill"
    src = tmp_path / "fill.c"
    src.write_text(r'''
#include <stdio.h>
#include <stdlib.h>
#include "sotto_prog.h"
int main(int argc, char **argv) {
  FILE *f = fopen(argv[1], "rb"); static unsigned char b[1 << 16], k[1 << 13];
  int n = (int)fread(b, 1, sizeof b, f) / 6; fclose(f);
  f = fopen(argv[2], "rb"); if (fread(k, 1, n, f) != (size_t)n) return 1; fclose(f);
  sotto_fparams_t *p = malloc(n * sizeof *p); unsigned char *rows = malloc(6 * n), *sg = malloc(n);
  sotto_prog_fill2400(b, k, n, p, rows, sg);
  for (int i = 0; i < n; i++) {
    printf("%d %d %d", p[i].code, p[i].wi, p[i].ei);
    for (int j = 0; j < 19; j++) printf(" %.17g", p[i].c[j]);
    printf("\n");
  }
  return 0;
}
''')
    c = os.path.join(ROOT, "c")
    subprocess.run(["cc", "-O2", "-std=c99", f"-I{c}", "-o", str(exe), str(src), os.path.join(c, "libsotto.a"),
                    "-lm"], check=True)
    bitf = os.path.join(ROOT, "docs/samples/rates/librispeech_3536_f__2400.bit")
    raw = np.frombuffer(open(bitf, "rb").read(), np.uint8)
    n = len(raw) // 6
    bits = np.unpackbits(raw[:6 * n]).reshape(n, 48).astype(np.int8)
    sc = sp.SCRIPTS["2400"]["SI"]
    rng = np.random.default_rng(7)
    cases = [sp.known_after("2400", n, sc, k) for k in (1, 2, 3, 5, 7)]
    cases += [{k: rng.random(n) < 0.6 for k in FIELDS} for _ in range(2)]
    cases.append({k: np.full(n, k in ("c", "w", "e")) for k in FIELDS})
    off = sp.offsets("2400")
    for known in cases:
        kb = np.zeros(n, np.uint8)
        for i, k in enumerate(FIELDS):
            kb |= known[k].astype(np.uint8) << i
        (tmp_path / "k.u8").write_bytes(kb.tobytes())
        out = subprocess.run([str(exe), bitf, str(tmp_path / "k.u8")], check=True, capture_output=True, text=True)
        pc = np.array([[float(v) for v in ln.split()] for ln in out.stdout.splitlines()])
        rx = bits.copy()
        for k in FIELDS:
            p, w = off[k]
            rx[~known[k], p:p + w] = 0
        fp = sp.partial_frames("2400", rx, known, hiss=True)
        assert np.array_equal(pc[:, 0], [q["code"] for q in fp])
        assert np.array_equal(pc[:, 1], [q["wi"] for q in fp])
        assert np.array_equal(pc[:, 2], [q["ei"] for q in fp])
        coef = (np.array([q["shape"] for q in fp]) @ np.linalg.pinv(vl.DCT))[:, 1:]
        assert np.max(np.abs(coef - pc[:, 3:])) < 1e-9
