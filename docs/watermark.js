// The harmonic phase watermark in the browser: loads watermark.wasm (watermark/c, the C port of
// watermark/harmonic.py, fec.py and fmchan.py with sotto's encoder pitch tracker) and runs the
// sender, the simulated FM channel and the receiver on 8 kHz Float32Array audio.
// Used by watermark.html; watermark/check_wasm.mjs runs it under node.
// SPDX-License-Identifier: MIT

const wasiStubs = { fd_write: () => 52, fd_seek: () => 52, fd_close: () => 52, proc_exit: () => {} };

export const FS = 8000;
export const SLOT_S = 256 / FS;
export const NCODE = 124;
export const BANDS = [
  { name: "wide", lo: 500, hi: 2600, nsub: 4 },
  { name: "narrow", lo: 900, hi: 2000, nsub: 2 },
];
export const CHANNELS = {
  direct: { kind: 0, label: "Direct (no radio)" },
  bandpass: { kind: 1, label: "300-3000 Hz voice filter only" },
  simplex25: { kind: 2, cnrIn: 25, label: "Simplex FM, 25 dB" },
  rpt40: { kind: 3, cnrIn: 40, cnrOut: 40, label: "Repeater, strong (40 dB both hops)" },
  rpt25: { kind: 3, cnrIn: 25, cnrOut: 25, label: "Repeater, 25 dB" },
  rptHot: { kind: 3, cnrIn: 25, cnrOut: 25, drive: 6, label: "Repeater, loud talker into the limiter" },
  rpt15: { kind: 3, cnrIn: 15, cnrOut: 25, label: "Repeater, noisy input (15 dB)" },
  rpt10: { kind: 3, cnrIn: 10, cnrOut: 25, label: "Repeater, weak input (10 dB)" },
};

export async function loadWatermark(source = "watermark.wasm") {
  const bytes = source instanceof ArrayBuffer || ArrayBuffer.isView(source)
    ? source : await (await fetch(source)).arrayBuffer();
  const { instance } = await WebAssembly.instantiate(bytes, { wasi_snapshot_preview1: wasiStubs });
  const x = instance.exports;
  x._initialize();
  return new Watermark(x);
}

class Watermark {
  constructor(x) { this.x = x; }

  _in(a) {
    const p = this.x.wm_alloc(4 * a.length);
    new Float32Array(this.x.memory.buffer, p, a.length).set(a);
    return p;
  }

  // -> { y: Float32Array, used: Uint8Array per slot, bits: Uint8Array (slots x nsub) }
  mark(x, call = "AG7EW", code = 0x5a, band = 0) {
    const X = this.x, n = x.length, ns = Math.floor(n / 256) + 1, nsub = BANDS[band].nsub;
    const px = this._in(x), py = X.wm_alloc(4 * n), pu = X.wm_alloc(ns), pb = X.wm_alloc(ns * nsub);
    const enc = new TextEncoder().encode(call.slice(0, 6).toUpperCase() + "\0");
    const pc = X.wm_alloc(enc.length);
    new Uint8Array(X.memory.buffer, pc, enc.length).set(enc);
    try {
      const m = X.wm_js_mark(px, n, pc, code & 255, band, py, pu, pb);
      return {
        y: new Float32Array(X.memory.buffer, py, n).slice(),
        used: new Uint8Array(X.memory.buffer, pu, m).slice(),
        bits: new Uint8Array(X.memory.buffer, pb, m * nsub).slice(),
        nsub,
      };
    } finally { [px, py, pu, pb, pc].forEach(p => X.wm_free(p)); }
  }

  channel(x, ch, seed = 1) {
    const X = this.x, n = x.length, c = typeof ch === "string" ? CHANNELS[ch] : ch;
    const px = this._in(x), py = X.wm_alloc(4 * n);
    try {
      X.wm_js_channel(px, n, c.kind, c.cnrIn ?? 30, c.cnrOut ?? 30, c.drive ?? 0, seed, py);
      return new Float32Array(X.memory.buffer, py, n).slice();
    } finally { X.wm_free(px); X.wm_free(py); }
  }

  // The receiver re-reading everything heard so far every `stepS` seconds (see wm_js_receive).
  receive(y, band = 0, stepS = 0.256) {
    const X = this.x, n = y.length, px = this._in(y);
    let pr = 0;
    try {
      pr = X.wm_js_receive(px, n, band, Math.max(256, Math.round(stepS * FS)));
      const h = new Float64Array(X.memory.buffer, pr, 8);
      const H = h[0], nsub = h[1], P = h[2], E = h[3], S = h[4], ew = 12 + NCODE, rw = 2 + nsub;
      const all = new Float64Array(X.memory.buffer, pr, H + P + E * ew + S * rw).slice();
      const pitch = all.subarray(H, H + P);
      const events = [];
      for (let i = 0; i < E; i++) {
        const e = all.subarray(H + P + i * ew, H + P + (i + 1) * ew);
        let call = "";
        for (let k = 0; k < 3; k++) {
          const v = e[9 + k], a = v % 256, b = Math.floor(v / 256);
          if (a) call += String.fromCharCode(a);
          if (b) call += String.fromCharCode(b);
        }
        events.push({
          t: e[0], offset: e[1], slots: e[2], cover: e[3], got: !!e[4], code: e[5], start: e[6],
          quality: e[7], confirmed: !!e[8], call: call.trim(), ring: e.slice(12, 12 + NCODE),
        });
      }
      const slots = [];
      const base = H + P + E * ew;
      for (let i = 0; i < S; i++) {
        const s = all.subarray(base + i * rw, base + (i + 1) * rw);
        slots.push({ t: s[0], event: s[1], soft: Array.from(s.subarray(2, 2 + nsub)) });
      }
      return { nsub, pitch, events, slots, firstId: h[5] < 0 ? null : h[5], offset: h[6] };
    } finally { X.wm_free(px); if (pr) X.wm_free(pr); }
  }
}

// Resampling to 8 kHz as scipy.signal.resample_poly does it: rational up/down, a Kaiser
// (beta 5) low-pass of 20 max(up, down) + 1 taps at the upsampled rate, zero phase
export function resampleTo8k(x, fs) {
  fs = Math.round(fs);
  if (fs === FS) return Float32Array.from(x);
  const gcd = (a, b) => (b ? gcd(b, a % b) : a), g = gcd(FS, fs), up = FS / g, down = fs / g;
  const mr = Math.max(up, down), half = 10 * mr, L = 2 * half + 1, fc = 1 / mr;
  const i0 = v => { let s = 1, t = 1; for (let k = 1; k < 40; k++) { t *= (v / (2 * k)) ** 2; s += t; } return s; };
  const h = new Float64Array(L), b0 = i0(5);
  let sum = 0;
  for (let i = 0; i < L; i++) {
    const m = i - half, r = (2 * i) / (L - 1) - 1;
    const sinc = m === 0 ? 1 : Math.sin(Math.PI * fc * m) / (Math.PI * fc * m);
    h[i] = fc * sinc * i0(5 * Math.sqrt(Math.max(0, 1 - r * r))) / b0;
    sum += h[i];
  }
  for (let i = 0; i < L; i++) h[i] *= up / sum;
  const n = Math.ceil(x.length * up / down), out = new Float32Array(n);
  for (let k = 0; k < n; k++) {
    const t = k * down + half;                    // index into conv(upsampled x, h)
    let acc = 0;
    for (let q = Math.max(0, Math.ceil((t - L + 1) / up)); q <= Math.floor(t / up) && q < x.length; q++)
      acc += x[q] * h[t - q * up];
    out[k] = acc;
  }
  return out;
}

// Speech level to -26 dBFS active level (the frames above the 30th loudness percentile)
export function levelTo(x, dbfs = -26) {
  const fr = 160, e = [];
  for (let i = 0; i + fr <= x.length; i += fr) {
    let s = 0; for (let k = i; k < i + fr; k++) s += x[k] * x[k];
    e.push(s / fr);
  }
  if (!e.length) return x;
  const sorted = [...e].sort((a, b) => a - b), thr = sorted[Math.floor(0.3 * sorted.length)];
  const act = e.filter(v => v > thr && v > 1e-10);
  if (!act.length) return x;
  const rms = Math.sqrt(act.reduce((a, b) => a + b, 0) / act.length);
  const g = Math.pow(10, dbfs / 20) / rms, out = new Float32Array(x.length);
  for (let i = 0; i < x.length; i++) out[i] = Math.max(-1, Math.min(1, x[i] * g));
  return out;
}
