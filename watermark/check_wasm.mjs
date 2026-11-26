// docs/watermark.wasm through docs/watermark.js under node, no build needed: a synthetic voice
// (a gliding harmonic comb with syllable gaps, as selftest.py) is marked, sent through the
// simulated repeater and decoded by the receiver; the unmarked voice must not decode.
//   node watermark/check_wasm.mjs [CLIP.wav ...]   also runs 8 kHz 16-bit WAV clips
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { loadWatermark, FS } = await import(join(root, "docs", "watermark.js"));
const wm = await loadWatermark(readFileSync(join(root, "docs", "watermark.wasm")));

function vowel(seconds = 10, seed = 1) {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
  const n = Math.round(seconds * FS), x = new Float32Array(n), ph = new Float64Array(30);
  for (let k = 1; k < 30; k++) ph[k] = 2 * Math.PI * rnd();
  let phi = 0;
  for (let i = 0; i < n; i++) {
    const t = i / FS, f0 = 120 + 15 * Math.sin(2 * Math.PI * 0.3 * t);
    phi += 2 * Math.PI * f0 / FS;
    // 1.2 s syllables with 0.3 s gaps, faded in and out
    const u = t % 1.5, env = u > 1.2 ? 0 : Math.min(1, u / 0.05, (1.2 - u) / 0.05);
    let v = 0;
    for (let k = 1; k < 30; k++) {
      const fk = k * f0;
      if (fk >= 3800) break;
      const a = Math.exp(-(((fk - 700) / 500) ** 2)) + 0.5 * Math.exp(-(((fk - 1500) / 400) ** 2)) + 0.05;
      v += a / Math.sqrt(k) * Math.cos(k * phi + ph[k]);
    }
    x[i] = 0.02 * env * v;
  }
  return x;
}

function readWav(path) {
  const b = readFileSync(path), dv = new DataView(b.buffer, b.byteOffset, b.length);
  let p = 12, fs = 0, out = null;
  while (p + 8 <= b.length) {
    const id = b.toString("ascii", p, p + 4), len = dv.getUint32(p + 4, true);
    if (id === "fmt ") fs = dv.getUint32(p + 12, true);
    if (id === "data") {
      out = new Float32Array(len / 2);
      for (let i = 0; i < out.length; i++) out[i] = dv.getInt16(p + 8 + 2 * i, true) / 32768;
    }
    p += 8 + len + (len & 1);
  }
  if (fs !== FS) throw new Error(`${path}: ${fs} Hz, want 8000`);
  return out;
}

let ok = true;
const check = (c, what) => { console.log((c ? "ok   " : "FAIL ") + what); ok &&= !!c; };

function run(name, x, channels) {
  for (const band of [0, 1]) {
    const t0 = Date.now();
    const m = wm.mark(x, "AG7EW", 0x5a, band);
    const tm = Date.now() - t0;
    const used = m.used.reduce((a, b) => a + b, 0) / m.used.length;
    for (const ch of channels[band]) {
      const t1 = Date.now();
      const z = wm.channel(m.y, ch);
      const r = wm.receive(z, band);
      const id = r.events.find(e => e.confirmed);
      check(id && id.call === "AG7EW" && id.code === 0x5a,
        `${name} band ${band} ${ch}: ID ${id ? `${id.call} 0x${id.code.toString(16)} at ${id.t.toFixed(2)} s, q ${id.quality.toFixed(2)}` : "none"}` +
        ` (marked ${(100 * used).toFixed(0)}% of slots; mark ${tm} ms, channel + receive ${Date.now() - t1} ms)`);
      const wrong = r.events.filter(e => e.confirmed && (e.call !== "AG7EW" || e.code !== 0x5a));
      check(!wrong.length, `${name} band ${band} ${ch}: no wrong IDs`);
    }
    const rc = wm.receive(wm.channel(x, channels[band][0]), band);
    check(!rc.events.some(e => e.got), `${name} band ${band} unmarked through ${channels[band][0]}: nothing decodes`);
  }
}

run("synthetic voice", vowel(), [["rpt25", "bandpass"], ["rpt40"]]);
for (const path of process.argv.slice(2))
  run(path.split("/").pop(), readWav(path), [["rpt40", "rpt25", "bandpass", "rpt10"], ["rpt40"]]);
console.log(ok ? "all ok" : "FAILED");
process.exit(ok ? 0 : 1);
