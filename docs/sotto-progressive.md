# Streamed and progressive sotto: one bitstream, two delivery orders

*2026-11-17. Design and feasibility study. Python reference `sim/sotto_prog.py`, scoring and
demos `tools/prog_race.py`, results `docs/results/prog_race.json` and
`docs/results/prog_loss.json`. Nothing here changes an existing mode's bitstream.*

## The idea

A stored or forwarded clip (a K6 VOICE MSG, a UV-380 FUNC recording, a Ragtime message) does
not have to go out in time order. Like a progressive JPEG, it can go out in *scans*: first the
coarse fields of every frame of the clip, then the finer ones. A receiver then has a rough copy
of the whole clip early, and it sharpens as the rest arrives. A station that loses the end of the
transmission, or loses packets in the middle, still has the whole message at lower quality,
instead of part of it at full quality.

The design keeps **one bitstream per mode**: the 48-bit superframes that sotto 2400, 1200, 600
and 400 already produce. Streamed and progressive are two **orders** of sending those same bits,
signalled per message:

| Order | What goes out | Use |
|---|---|---|
| **Streamed** | superframes in time order (today's format, slot-interleaved in K6 packets) | live audio, lowest latency |
| **Progressive** | one block = the whole clip, sent scan by scan | stored clips |
| **Block-progressive** | blocks of a few seconds, each sent scan by scan | live audio over a weak link |

After the last scan the receiver holds exactly the streamed superframes. The full decode is the
existing decoder on the existing bits, so every C port stays bit-exact with no change. Only a
receiver that plays a clip *before* it is complete, or with packets missing, needs something new:
a small fill step that supplies the missing fields (section 4).

## 1. What the measurements say

Sixteen held-out voices (`/mnt/project-files/vocoder/samples-clean/`), mean PESQ-NB / ESTOI,
whole-utterance pitch tracker, as in `docs/sotto-1200.md`. "Share" is the share of the clip's
bits received.

**Pitch and energy alone don't carry words.** With voicing, pitch and energy for every frame
(29% of a sotto 2400 clip) and a fixed spectral shape per voicing class, the clip scores PESQ
1.28 and ESTOI 0.15: you hear the talker's rhythm, intonation and pauses, but not the words. The
words arrive with the first shape stage. So the recommended first scan sends pitch, energy *and*
the first 9-bit shape stage, for every other 20 ms frame. That gives an intelligible rough clip at
**24%** of the air time, sooner than the third Jeff hoped for.

**sotto 2400, script SI** (the recommended order):

| Scan | Adds | Share | PESQ | ESTOI | Close to |
|---:|---|---:|---:|---:|---|
| 1 | voicing, pitch, energy and shape stage 1 of even frames | 24.0% | 1.97 | 0.649 | sotto 600 (2.15 / 0.692) |
| 2 | voicing, pitch, energy of odd frames | 38.5% | 2.14 | 0.670 | |
| 3 | shape stage 1 of odd frames | 47.9% | 2.29 | 0.703 | |
| 4 | shape stage 2, even frames | 57.3% | 2.45 | 0.736 | |
| 5 | shape stage 2, odd frames | 66.7% | 2.65 | 0.770 | sotto 1200 (2.61 / 0.763) |
| 6 | shape stage 3 | 83.3% | 2.80 | 0.799 | |
| 7 | shape stage 4: the streamed clip, bit for bit | 100% | 2.94 | 0.817 | |

Other orders tried (`docs/results/prog_race.json`): pitch and energy first, then whole shape
stages (P: 1.28 at 29%, 2.29 at 48%, 2.65 at 67%), the same with time interlacing (PI, PII). SI
is as good as the best of them at every share and much better early.

**sotto 1200, script SI:**

| Scan | Adds | Share | PESQ | ESTOI |
|---:|---|---:|---:|---:|
| 1 | A frame's voicing, pitch, energy and shape stage 1, even superframes | 24.0% | 1.51 | 0.508 |
| 2 | the same, odd superframes | 47.9% | 2.02 | 0.657 |
| 3 | B frame's voicing, pitch and energy steps | 64.6% | 2.16 | 0.673 |
| 4 | A's shape stage 2 | 83.3% | 2.44 | 0.733 |
| 5 | B's shape residual: the streamed clip | 100% | 2.61 | 0.763 |

**sotto 600 and 400, script SI:** 600 gives 1.41 / 0.473 at 46% and 1.88 / 0.620 at 77%; 400
gives 1.29 / 0.388 at 50% and 1.68 / 0.574 at 83%. These modes are already lean (half their bits
are voicing, pitch and energy), so a scan order gains them little. They are better used *as* the
coarse copy (section 7).

**The price of reusing the same bits.** At the same share, a scan prefix sounds a little worse
than a codec built for that rate: sotto 2400 at 24% gives 1.97 against sotto 600's 2.15 at 25%,
and at 48% 2.29 against sotto 1200's 2.61 at 50%. In return the progressive order costs no extra
air time at all, and the complete clip is the 2400 clip.

## 2. Loss: where progressive really pays

Packets are XL-sized (120 speech bytes). Streamed packets carry today's slot interleave (packet
k of a group of 8 carries slots k, k+8, ...). Progressive packets carry consecutive stretches of
the scan stream; inside each scan the superframes go in a spread order (section 3), so a lost
packet takes one kind of field from frames spread over the block and every gap has neighbours.

"Parity" for streamed is the K6's section-14 XOR packet, one per 8 data packets (12.5% more air
time). For progressive the same 12.5% goes to the front: one XOR packet per 4 packets over the
first half of each block's packets, where the first scans are.

Mean PESQ / ESTOI over the 16 voices, `docs/results/prog_loss.json`. "Random" loses each
packet independently (seeded per clip); "1 in 8" loses packet 3 of every 8. "Clip" sends the
whole clip as one block, "group" in blocks of 160 superframes.

**sotto 2400**

| Packet loss | Streamed | Streamed + parity | Progressive, clip | Progressive, clip + front parity | Progressive, group + front parity |
|---|---:|---:|---:|---:|---:|
| 5% random | 2.73 / 0.805 | 2.88 / 0.813 | 2.81 / 0.803 | 2.90 / 0.813 | **2.91 / 0.813** |
| 10% random | 2.55 / 0.787 | 2.69 / 0.797 | 2.65 / 0.786 | **2.82 / 0.804** | 2.79 / 0.801 |
| 20% random | 2.29 / 0.754 | 2.43 / 0.768 | 2.43 / 0.750 | **2.61 / 0.774** | 2.51 / 0.758 |
| 1 in 8 | 2.45 / 0.783 | **2.94 / 0.817** | 2.54 / 0.769 | 2.83 / 0.802 | **2.94 / 0.817** |

**sotto 1200**

| Packet loss | Streamed | Streamed + parity | Progressive, clip | Progressive, clip + front parity | Progressive, group + front parity |
|---|---:|---:|---:|---:|---:|
| 5% random | 2.36 / 0.735 | 2.52 / 0.752 | 2.40 / 0.737 | **2.58 / 0.758** | **2.58 / 0.759** |
| 10% random | 2.14 / 0.702 | 2.30 / 0.721 | 2.21 / 0.706 | 2.41 / 0.736 | **2.43 / 0.736** |
| 20% random | 1.89 / 0.649 | 1.97 / 0.660 | 1.98 / 0.653 | **2.14 / 0.684** | 2.07 / 0.669 |
| 1 in 8 | 2.18 / 0.712 | **2.61 / 0.763** | 2.09 / 0.695 | 2.50 / 0.745 | 2.58 / 0.759 |

- **For sotto 2400 and 1200, progressive with front parity beats today's streamed order with
  parity at every random loss rate, for the same air time**: by 0.13 PESQ at 10% loss and 0.18 at
  20% in sotto 2400, by 0.11-0.17 in sotto 1200. At 20% loss a progressive sotto 2400 clip scores
  what streamed scores at 10%. Even with no parity at all, progressive beats streamed without
  parity.
- **Why:** a lost streamed packet takes 20 whole slots; a lost progressive packet takes one kind
  of field from frames spread over the block, which the neighbours fill, and the parity sits on
  the fields that matter most. When losses are exactly one per 8 packets, the streamed parity
  rebuilds every one of them, and so does progressive with blocks of 160 superframes; front
  parity on a whole clip leaves the back half's losses to the fill (2.83 against 2.94).
- **sotto 600 and 400 should stay streamed.** Half their bits are voicing, pitch and energy, so
  a lost progressive packet hurts as much as a lost slot and the fill has less to work with
  (600 at 10% loss: 1.93 either way with parity, 1.58 against 1.82 without).
- These are independent losses. Real fades come in bursts that take several packets in a row;
  the spread order inside each scan is what keeps a burst from taking neighbouring frames, but a
  burst run (Rayleigh fading through `sim/c4fm_sim.py`) is still to do.

## 3. The scan stream

### Fields and scans

Each mode's superframe is a list of fields (`layout()` in the Python references):

| Mode | Fields (bits) |
|---|---|
| 2400 | c 2, w 7, e 5, s0 9, s1 9, s2 8, s3 8 (voicing, pitch, energy, four shape stages) |
| 1200 | ca 2, wa 7, ea 5, sa0 9, sa1 9, cb 2, dw 3, de 3, sb 8 |
| 600 | v 3, wc 7, ws 3, em 5, er 5, a0s0 7, a0s1 6, a1s0 7, a1s1 5 |
| 400 | v 3, wc 7, ws 3, em 5, er 5, a0s0 9, a1s0 8, a2s0 8 |

A **scan** is a set of fields for one phase of the block's superframes: all of them (step 1), or
the even or odd ones (step 2). A **script** is the ordered list of scans and covers every field
of every superframe exactly once. Version 1 defines one script per mode, SI:

```
2400  (c w e s0)/even  (c w e)/odd  s0/odd  s1/even  s1/odd  s2  s3
1200  (ca wa ea sa0)/even  (ca wa ea sa0)/odd  (cb dw de)  sa1  sb
600   (v wc em a0s0)  (ws er a1s0)  (a0s1 a1s1)
400   (v wc em a0s0)  (ws er a2s0)  a1s0
```

### Order inside a scan

A scan over n superframes (the block's superframes of that phase, in time order, indexed 0..n-1)
puts superframe j at position `j * Q mod n`, with `Q = golden_step(n)`: the integer nearest
0.382 n (n / phi^2) that shares no factor with n (1 when n <= 2). Neighbouring superframes then
sit about 0.38 n positions apart, so a lost run shorter than that (one lost packet in a scan of
more than three packets' worth) never takes two neighbours, and by the three-gap theorem the
superframes it does take are spread evenly over the block. Position i carries superframe
`i * Q^-1 mod n`. Sender and receiver need Q^-1 once per scan size (extended Euclid), then one
multiply and a modulo per item, so a Cortex-M0 needs no table. Each item's fields go in layout
order, MSB first, and scans follow each other with no padding. The block's stream is cut into
packet payloads with no padding until the last.

### Blocks

A block is `B` superframes; the clip is cut into blocks from the start, and the last may be
shorter. B = the whole clip is the stored-clip case. For live audio, B matches the K6's
interleave group (160 slots in XL at depth 8, 80 at depth 4), so block-progressive adds no
latency on the K6, which already waits for a whole group before it plays it.

## 4. Decoding a partial block

A field is **known** when every one of its bits has arrived. The decoder rebuilds per-20 ms frame
parameters (voicing code, 7-bit pitch index, energy code, shape as DCT coefficients 1..19) and
runs the v3.7 decoder core that every mode already shares (`sotto_dec_frame` in the C ports):

- **Voicing, pitch or energy missing:** from the nearest frames that have them, by sotto 1200's B
  rule: pitch `(a + b + 1) >> 1` when both are voiced, else the voiced one's; energy
  `(a + b + 1) >> 1`; voicing copied from the nearer neighbour, an edge code read as mixed. In
  600/400 a missing slope or energy residual is the table entry nearest zero.
- **Some shape stages missing:** the sum of the stages that have arrived, as long as stage 1 is
  one of them. Each stage of the multistage codebook refines the stages before it, so a prefix of
  stages is a coarser shape. 1200's B shape uses its anchors' partial shapes, plus its residual
  once that is known.
- **No shape stage for a frame:** linear in time between the nearest frames (or anchors) that
  have one.
- **No shape anywhere yet:** a prior shape per voicing code, 4 x 19 values
  (`sim/data/prog_prior.npz`, 76 bytes as int8; trained by `tools/prog_race.py --train-prior` on
  the six Codec 2 reference clips, none of them in the test set).

Then the normal decoder runs. When every field is known this is the streamed decode exactly
(checked in all four modes: identical samples, `tests/test_prog.py`).

## 5. Signalling

### Clip container (files, message stores, the UV-380 player, Ragtime)

Streamed `.sot` files stay as they are: raw 6-byte slots. A clip that needs its order said
carries a 12-byte header:

| Bytes | Field |
|---|---|
| 0-3 | `S O T P` |
| 4 | version, 1 |
| 5 | mode: 0 = 2400, 1 = 1200, 2 = 600, 3 = 400; bit 7 set = the frames carry the 4-8 kHz hiss layer (same layout) |
| 6 | order: 0 = streamed, 1 = progressive |
| 7 | script: 1 = SI (0 for streamed) |
| 8-9 | block length B in superframes, big-endian; 0 = the whole clip |
| 10-11 | total superframes, big-endian |

Then the payload: the superframes in time order (streamed), or each block's scan stream in
order, the last padded with zero bits to a whole byte (progressive). A receiver that keeps clips
(the UV-380 player, a K6 store) keeps them as streamed slots once reassembled; the header is a
transport matter.

### K6 / UV-380 pager packets

Today's voice packets keep their magics (0xA7, 0xA9, 0xAC, 0xAD) and their parity packets
(| 0x10). Progressive packets take the codec's magic + 0x20, their parity packets that | 0x10:

| Mode | Streamed | Its parity | Progressive | Its parity |
|---|---|---|---|---|
| 2400 | 0xA7 | 0xB7 | **0xC7** | **0xD7** |
| 1200 | 0xA9 | 0xB9 | **0xC9** | **0xD9** |
| 600 | 0xAC | 0xBC | **0xCC** | **0xDC** |
| 400 | 0xAD | 0xBD | **0xCD** | **0xDD** |

Old receivers drop them cleanly: the K6 checks for its exact magics, and the UV-380's
`pager_rx.c` takes only 0xA_ magics as voice.

Progressive XL payload (PN9 whitening and CRC as today):

| Bytes | Field |
|---|---|
| 0 | magic (table above) |
| 1 | msg_id |
| 2-3 | packet number in the message (13 bits; bits 15-13 zero, as no depth or short-last flag applies) |
| 4-5 | total superframes |
| 6 | bits 7-5: script (1 = SI); bits 4-0: block, in units of 20 superframes (1-31, so a block fits the K6's 640-slot ring); 0 = the whole message |
| 7-125 | 119 bytes = 952 bits of the scan stream |
| 126-127 | CRC-16/CCITT-FALSE |

Packets per block = ceil(B x 48 / 952), so a receiver knows from `total`, the block byte and the
packet number exactly which bits a packet carries, and which are lost when it doesn't come. One
progressive parity packet follows every 4 packets of the first half of a block (ceil(n/2)
packets for an n-packet block), its body the XOR of theirs, so a single loss among them comes
back. A sender over a very weak path may also send the first half of a block twice (section 6
of the packet spec already allows repeats with the same msg_id).

### What a receiver does in each order

- **Streamed:** as today.
- **Progressive or block-progressive:**
  1. Keep the store as streamed slots and a bitmap of the packets received (a 12 s sotto 2400 clip
     is 31 packets, so 4 bytes).
  2. Scatter each good packet's 952 bits into the slots by the scan order.
  3. When a block is complete, or nothing more arrives for 3 s (the spec's rule), play it,
     filling unknown fields by section 4. A field is known when the packets holding all its bits
     are in.
  4. A receiver may also **preview**: start playing once the first scan of the clip is in, reading
     each slot from the store as it plays it. Later scans keep landing during playback, so the
     clip sharpens as it plays (section 6).

## 6. Timing on the K6 and the 2400-baud path

A 12 s clip in XL packets (952 bits each for progressive, 960 for streamed), 12-byte preambles
between packets:

| | Packets | F/1800 on air | Rough clip (scan 1) | D/2400 on air | Rough clip |
|---|---:|---:|---:|---:|---:|
| sotto 2400 | 31 | 19.8 s | 4.8 s | about 14.9 s | 3.6 s |
| sotto 1200 | 16 | 10.2 s | 2.5 s (1.51), 4.9 s (2.02) | about 7.7 s | 1.8 s |

(D/2400 is the chip FSK that the K6 receives perfectly from a flat transmitter such as the Pluto
or the UV-380's C6000 PHY, 12-15 dB more sensitive than F/1800; blowfang `docs/k6-fsk24.md`. The
progressive bitstream is the same on any PHY.)

**Preview while it plays.** sotto 2400 over F/1800 runs at 1.65 times real time, so streamed
playback has to wait for most of the clip or it runs dry. A progressive receiver can start at
4.8 s; when it reaches the clip's last second (16.8 s) it already has 85% of the bits (scan 6),
so the clip starts rough and is close to full quality by the end. For sotto 1200 (0.85 times
real time) streaming already starts in about 3.75 s at depth 4 at full quality, so on a clean
link progressive mostly helps when packets are lost or the transmission is cut short.

**Live audio** goes block-progressive with B = the interleave group: the K6's ring, the 3.2 s
groups of `tools/k6_talk.py` and the latency (about 6.3 s at depth 4) are unchanged. What changes
is what a lost packet costs (section 2).

## 7. A coarse copy first (option, not in version 1)

For the leanest preview, a sender can put a whole sotto 400 or 600 copy of the clip in front
(17% or 25% more air time), then the streamed or progressive clip. At 25% of the main clip's air
time the 600 copy scores 2.15 where the SI prefix scores 1.97, but the total air time is 125%.
The container can carry it as a second track later if a use needs it. A truly embedded codec,
whose fine layers are trained to refine a sotto 400 base instead of reusing today's bits, would
get both, but it is a new codec with new tables (and the K6 flash has no room for them).

## 8. Effect on the C ports and the radios

- **Encoders:** unchanged. Progressive is a reorder after encoding; a sender needs the whole
  clip (progressive) or one block (block-progressive) in RAM: 3.6 KB for a 12 s sotto 2400 clip.
- **Full decode:** unchanged and bit-exact, since the reassembled slots are the streamed slots.
- **Partial decode:** new code in front of the existing frame decoder: the scatter (golden step and
  its inverse), the known test from the packet bitmap, the fill rules and the 76-byte prior. The
  fixed-point decoders already take per-frame fields (`fx_fparams_t`: code, wi, ei, shape
  coefficients), as sotto 1200 and 600/400 build them, so the core doesn't change. The fill
  rules are integer except the time interpolation of shapes, which the fixed decoder does in its
  Q16 dB format like sotto 600's anchors; the check is the usual one (`tools/check_fx.py`
  style: same bits, SNR against the float).
- **K6:** reassembly alone (scatter plus packet bitmap) is small, and with it a complete
  progressive message plays bit-exact through today's player. The fill step can come second; in
  sotto 1200 a slot whose shapes are missing can already play through the decoder's `good = 2`
  path (voicing, pitch and energy trusted, shapes from the last good superframe). The K6's flash
  is nearly full, so the first K6 step should be an OTA RAM module that reassembles a progressive
  message into the store and hands it to the player, if the module API reaches the store;
  otherwise a core change sized against the free flash.
- **UV-380:** its `pager_rx.c` gains the 0xC_ magics and the scatter; the FUNC recorder already
  has the whole clip before it sends, so it can send progressive by default.
- **Pause frames** (K6 senders compact silent runs): a pause frame's marker is in its shape bits,
  which arrive late. Until they do, the frame decodes as voicing 0, energy 0: one silent slot, so a
  pause plays short in a preview and right once complete.

## 9. Next steps

1. A blind listening round: the SI scans against sotto 600 / 1200 at the same share, and the 10%
   loss pairs, to check by ear what PESQ says.
2. `modem.k6 tx --order progressive` and `rx` in blowfang (Python, host only), with the
   packet loss runs above repeated through `tools/k6_pcmhash.py`.
3. The C fill layer in `c/` and `c/fixed/`, then the K6 receiver (module first) and the UV-380.

## Use

```sh
python tools/prog_race.py                       # scans, 16 voices, all modes -> stdout (--json OUT)
python tools/prog_race.py --loss every8,rate0.1 # packet loss, streamed vs progressive
python tools/prog_race.py --demo CLIP.flac --mode 2400 --script SI --out build/prog-demo
python tools/prog_race.py --train-prior         # sim/data/prog_prior.npz
```

The race caches each clip's encoded bits in `build/prog-cache/` (`PROG_CACHE` to move it).
