// node c/wasm/check_tts.mjs c/wasm/sotto_tts.wasm c/tts/sotto_tts
// sotto_tts.wasm must give the same superframes and samples as the native tool (sotto_tts -pcm).
// SPDX-License-Identifier: MIT
import { readFileSync, mkdtempSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [wasmPath, exe] = process.argv.slice(2);
const stub = () => 52;
const { instance } = await WebAssembly.instantiate(readFileSync(wasmPath), {
  wasi_snapshot_preview1: { fd_write: stub, fd_seek: stub, fd_close: stub, fd_fdstat_get: stub,
    environ_get: () => 0, environ_sizes_get: () => 0, proc_exit: () => {}, clock_time_get: stub },
});
const x = instance.exports;
x._initialize?.();
const texts = ["This is AG7EW on 440.850 MHz.", "Is the repeater on, please?",
               "KD7ABC/P calling CQ, over. The birch canoe slid on the smooth planks."];
const dir = mkdtempSync(join(tmpdir(), "tts-"));
let bad = 0;
for (const table of [0, 1]) {
  for (const s of texts) {
    const mem = () => new Uint8Array(x.memory.buffer);
    const enc = new TextEncoder().encode(s);
    mem().set(enc, x.tts_text());
    mem()[x.tts_text() + enc.length] = 0;
    const n = x.tts_say(table, 1.0, 1.0);
    const sf = mem().slice(x.tts_superframes(table), x.tts_superframes(table) + 6 * n);
    const pcm = new Int16Array(x.memory.buffer, x.tts_pcm(), x.tts_npcm()).slice();
    execFileSync(exe, [...(table ? ["-robot"] : []), "-pcm", join(dir, "o.raw"), s, join(dir, "o.sot")]);
    const rsf = readFileSync(join(dir, "o.sot"));
    const rb = readFileSync(join(dir, "o.raw"));
    const rpcm = new Int16Array(rb.buffer, rb.byteOffset, rb.length / 2);
    const same = Buffer.compare(Buffer.from(sf), rsf) === 0 && pcm.length === rpcm.length &&
                 pcm.every((v, i) => v === rpcm[i]);
    if (!same) bad++;
    console.log(`${same ? "ok  " : "DIFF"} table ${table} ${n} superframes ${pcm.length} samples: ${s}`);
  }
}
process.exit(bad ? 1 : 0);
