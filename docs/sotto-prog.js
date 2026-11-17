// Progressive sotto 2400 delivery orders (docs/sotto-progressive.md sections 3 and 6), the
// JavaScript twin of sim/sotto_prog.py's order() and jit_order(). A clip's 48-bit frames are
// cut into items (one field of one frame) and sent in one of three orders:
//   streamed     every field of frame 0, then frame 1, ... (time order)
//   progressive  scan by scan (script SI); inside a scan the frames go in the golden-step order
//   jit          just in time: the first scan, then each frame's other fields while they can
//                still land before the frame plays on a link of `ratio` seconds of air time per
//                second of speech, then what didn't fit
// tests/test_prog_web.py checks these against the Python reference.
// SPDX-License-Identifier: MIT

// sotto 2400's frame: voicing, pitch, energy, then the four shape stages (bits, MSB first)
export const FIELDS = [
  { key: "c", bits: 2, pos: 0, name: "voicing" },
  { key: "w", bits: 7, pos: 2, name: "pitch" },
  { key: "e", bits: 5, pos: 9, name: "energy" },
  { key: "s0", bits: 9, pos: 14, name: "shape 1" },
  { key: "s1", bits: 9, pos: 23, name: "shape 2" },
  { key: "s2", bits: 8, pos: 32, name: "shape 3" },
  { key: "s3", bits: 8, pos: 40, name: "shape 4" },
];
export const FRAME_BITS = 48;
export const FRAME_MS = 20;

// Script SI: [field indices, step, phase]; step 2 phase 0/1 = even / odd frames
export const SCRIPT_SI = [
  { fields: [0, 1, 2, 3], step: 2, phase: 0, what: "voicing, pitch, energy, shape 1 of even frames" },
  { fields: [0, 1, 2], step: 2, phase: 1, what: "voicing, pitch, energy of odd frames" },
  { fields: [3], step: 2, phase: 1, what: "shape 1 of odd frames" },
  { fields: [4], step: 2, phase: 0, what: "shape 2, even frames" },
  { fields: [4], step: 2, phase: 1, what: "shape 2, odd frames" },
  { fields: [5], step: 1, phase: 0, what: "shape 3" },
  { fields: [6], step: 1, phase: 0, what: "shape 4" },
];

const gcd = (a, b) => { while (b) [a, b] = [b, a % b]; return a; };

// Python's round(): halves to even
function roundHalfEven(x) {
  const f = Math.floor(x), d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

// Q: the integer nearest n / phi^2 (0.382 n) that shares no factor with n (1 when n <= 2)
export function goldenStep(n) {
  if (n <= 2) return 1;
  let q = Math.max(1, roundHalfEven(n * 0.3819660112501051));
  while (gcd(q, n) !== 1) q++;
  return q;
}

function modInverse(a, n) {
  let [r0, r1, t0, t1] = [n, a % n, 0, 1];
  while (r1) {
    const q = Math.floor(r0 / r1);
    [r0, r1] = [r1, r0 - q * r1];
    [t0, t1] = [t1, t0 - q * t1];
  }
  return ((t0 % n) + n) % n;
}

// the frames `sel` (in time order) as one scan sends them: position i carries sel[i * Q^-1 mod n]
export function spreadOrder(sel) {
  const n = sel.length;
  const qi = n > 1 ? modInverse(goldenStep(n), n) : 0;
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = sel[(i * qi) % n];   // i * qi < 2^53 for any clip
  return out;
}

// Items of the progressive order: [{ sf, f }], and the bit count at the end of each scan
export function progressiveOrder(ns, script = SCRIPT_SI) {
  const items = [], ends = [];
  let bits = 0;
  for (const sc of script) {
    const sel = [];
    for (let s = sc.phase; s < ns; s += sc.step) sel.push(s);
    for (const s of spreadOrder(sel))
      for (const f of sc.fields) { items.push({ sf: s, f }); bits += FIELDS[f].bits; }
    ends.push(bits);
  }
  return { items, ends };
}

export function streamedOrder(ns) {
  const items = [];
  for (let s = 0; s < ns; s++) for (let f = 0; f < FIELDS.length; f++) items.push({ sf: s, f });
  return { items, ends: [ns * FRAME_BITS] };
}

// sim/sotto_prog.jit_order(mode, ns, script, nbase, ratio, lag)
export function jitOrder(ns, ratio, script = SCRIPT_SI, nbase = 1, lag = 0) {
  const { items } = progressiveOrder(ns, script);
  let nb = 0;
  for (const sc of script.slice(0, nbase)) nb += Math.ceil(Math.max(0, ns - sc.phase) / sc.step) * sc.fields.length;
  const base = items.slice(0, nb);
  const have = new Set(base.map(it => it.sf * 8 + it.f));
  const prio = [];
  for (const sc of script) for (const f of sc.fields) if (!prio.includes(f)) prio.push(f);
  const baseBits = base.reduce((a, it) => a + FIELDS[it.f].bits, 0);
  let cum = baseBits;
  const out = base.slice(), late = [];
  let fitEnd = 0;
  for (let sf = 0; sf < ns; sf++) {
    const budget = baseBits + Math.max(0, sf - lag) * FRAME_BITS / ratio;
    for (const f of prio) {
      if (have.has(sf * 8 + f)) continue;
      if (cum + FIELDS[f].bits <= budget) { out.push({ sf, f }); cum += FIELDS[f].bits; }
      else late.push({ sf, f });
    }
  }
  fitEnd = cum;
  return { items: out.concat(late), ends: [baseBits, fitEnd, ns * FRAME_BITS] };
}

// The order as typed arrays: frame, field, first bit and width of every item, in sending order
export function buildStream(ns, order, ratio = 1) {
  const o = order === "streamed" ? streamedOrder(ns) : order === "jit" ? jitOrder(ns, ratio) : progressiveOrder(ns);
  const n = o.items.length;
  const sf = new Int32Array(n), f = new Uint8Array(n), start = new Int32Array(n), end = new Int32Array(n);
  let b = 0;
  o.items.forEach((it, i) => {
    sf[i] = it.sf; f[i] = it.f; start[i] = b; b += FIELDS[it.f].bits; end[i] = b;
  });
  return { order, ratio, ns, n, sf, f, start, end, totalBits: b, ends: o.ends };
}

// copy field f of frame s from `src` frames into `dst` frames (both 6 bytes per frame)
export function copyField(src, dst, s, f) {
  const { pos, bits } = FIELDS[f];
  for (let i = 0; i < bits; i++) {
    const p = s * FRAME_BITS + pos + i, byte = p >> 3, m = 0x80 >> (p & 7);
    dst[byte] = (dst[byte] & ~m) | (src[byte] & m);
  }
}
