# Cortex-M4 bench (TYT MD-UV380/390, Module17, CS7000)

A cycle estimate for the fixed-point sotto on the STM32F405 (Cortex-M4, 168 MHz) that the
OpenRTX radios use, without a board: a bare-metal build run one frame at a time in an
instruction emulator, every executed instruction costed with the Cortex-M4's published
timings.

```sh
pip install unicorn capstone             # the emulator and the disassembler
sh tools/cm4_build.sh                    # c/fixed/cm4/build/bench.elf (clang + lld, -O2)
python c/fixed/cm4/run.py c/fixed/cm4/build/bench.elf in.raw --bits m4.bit
make -C c fixed && c/fixed/sotto_enc_fx in.raw x86.bit && cmp m4.bit x86.bit
```

`in.raw` is 8 kHz 16-bit mono (or a .wav). The output is the encoder's and decoder's MHz for
real time (mean and worst frame), heap, stack and flash bytes. For v3.8 at 16 kHz:
`VARIANT=v3.8 sh tools/cm4_build.sh`, then `run.py ... in16k.raw --16k --bits m4.bit --pcm
m4.raw`, and compare with `sotto_enc_fx -16` and `sotto_dec_fx -16`. `--profile` adds the
encoder's MHz by function, and `--flash` adds the STM32F4's flash wait states (slow, so use
`--frames 100`). `sh tools/cm4_build.sh -Os` gives the size-optimised build that OpenRTX
uses by default.

sotto 1200 (48 bits per 40 ms): `VARIANT=v3.8 LR=1 sh tools/cm4_build.sh` links `lr.elf`, and
`run.py c/fixed/cm4/build/lr.elf in.raw --lr --bits m4.bit --pcm m4.raw` times its encoder and
decoder apart, 320 samples a call; compare with `sotto_enc_fx -1200` and `sotto_dec_fx -1200`.
`LR16=k6` (the K6's hiss layer) or `LR16=full` (v3.8's) also links `lr16.elf` for sotto 1200
hiss at 16 kHz (`--lr16`, 640 samples a call; `sotto_enc_fx -16 -1200`, and `sotto_dec_fx_k6` or
`sotto_dec_fx -16 -1200`). While a build's encoder is a stub, `--dec-bits IN.bit` feeds the
decoder. `--no-prefetch` runs the flash model with the ART prefetch off, as OpenRTX's
`SystemInit` leaves it. `FPU=1` builds with the radio's float ABI (`-mfpu=fpv4-sp-d16
-mfloat-abi=hard`); the code is integer only, and clang's image comes out byte for byte the same.
`CM4_CC=arm-none-eabi-gcc` compiles with GCC (OpenRTX's compiler; tested with 13.2.1 from Ubuntu's
`gcc-arm-none-eabi`), still linked by lld.
`sh tools/cm4_lr_check.sh [-Os]` does all of it against the x86 tools and prints the table (CI's
`cm4-sotto-1200` job). Results: `docs/c-port.md`, "sotto 1200 on the Cortex-M4 (UV-380)".

Files: `shim.c` (bump allocator, memory functions, 64-bit division), `divmod.s` (the ABI's
64-bit division entry points), `inc/` (C library header stand-ins), `link.ld`, `run.py`
(the emulator, the timing model and the flash model, described in its docstring).

The code that runs on the M4 is the ordinary `c/fixed/` C. `FX_ARM_DSP` (fx.h) is on for any
ARM target with the DSP extension. It takes 32 x 32-bit products directly (`FX_WIDE_MUL`),
because the M4's SMULL and SMLAL take one cycle, searches an unpacked codebook with SMLAD,
and does the 16-bit dot products (resamplers, minimum phase), the overlap-add and the NLP
pitch DFT with SMLALD/SMLSLD, two products per instruction into 64 bits. Results and the method's limits are in `docs/c-port.md`, "Fixed point on the
Cortex-M4".

SPDX-License-Identifier: MIT
