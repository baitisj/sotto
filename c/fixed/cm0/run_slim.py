#!/usr/bin/env python3
"""The slim sotto 1200 encoder (../sotto_fx_slim.c, docs/sotto-slim.md) on the Cortex-M0 cycle
bench: run.py's machine and timing model, 10 ms blocks in, superframes out.

  sh tools/cm0_slim_build.sh -Oz
  python3 c/fixed/cm0/run_slim.py [--elf SLIM.elf] [--ws N] [--profile] [--bits OUT.bit] IN.raw

Prints the clock the encoder needs for real time (MHz: mean, 99th percentile and worst 40 ms
superframe), its state and stack, and the image's size (codebook included). --ws: flash wait
states (0: code in RAM, as a K6 module runs; 2: the K6's flash). --bits writes the superframes,
to compare with fixed/sotto_slim_enc's. Needs unicorn.
SPDX-License-Identifier: MIT"""
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cm0_run", os.path.join(HERE, "run.py"))
cm0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm0)
cm4 = cm0.cm4


def main():
    a = sys.argv[1:]
    ws, bits, elf = 0, None, os.path.join(HERE, "build-slim", "slim.elf")
    if "--ws" in a:
        i = a.index("--ws"); ws = int(a[i + 1]); del a[i:i + 2]
    if "--bits" in a:
        i = a.index("--bits"); bits = a[i + 1]; del a[i:i + 2]
    if "--elf" in a:
        i = a.index("--elf"); elf = a[i + 1]; del a[i:i + 2]
    prof = "--profile" in a
    if prof:
        a.remove("--profile")
    cm0.WS = ws
    m = cm0.M0(elf)
    pcm = open(a[0], "rb").read()
    st, io = cm4.IO + 0x10000, cm4.IO
    nbytes, _ = m.call("slim_enc_bytes")
    m.call("slim_enc_init", st)
    m.paint_stack()
    n = len(pcm) // 640
    cyc, out = [], b""
    m.prof = collections.Counter() if prof else None
    for i in range(n):
        c40 = 0
        for k in range(4):
            m.mu.mem_write(io, pcm[640 * i + 160 * k:640 * i + 160 * k + 160])
            r, c = m.call("slim_encode10", st, io, io + 0x1000)
            c40 += c
            if r:
                out += bytes(m.mu.mem_read(io + 0x1000, 6))
        cyc.append(c40)
    p, m.prof = m.prof, None
    while m.call("slim_flush", st, io + 0x1000)[0]:
        out += bytes(m.mu.mem_read(io + 0x1000, 6))
    if bits:
        open(bits, "wb").write(out)
    srt = sorted(cyc)
    res = {"ws": ws, "blocks_40ms": n, "MHz_mean": round(sum(cyc) / n * 25 / 1e6, 2),
           "MHz_p99": round(srt[int(0.99 * (n - 1))] * 25 / 1e6, 2), "MHz_worst": round(srt[-1] * 25 / 1e6, 2),
           "state_bytes": nbytes, "stack_bytes": m.stack_used(), "image_bytes": len(m.img)}
    if p:
        res["profile_MHz"] = {k: round(v / n * 25 / 1e6, 2) for k, v in p.most_common(16)}
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
