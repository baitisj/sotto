#!/bin/sh
# Build the fixed-point sotto (8 kHz v3.7, or 16 kHz v3.8) for a Cortex-M4 with clang and lld, bare metal, for
# the cycle bench in c/fixed/cm4/run.py: c/fixed/cm4/build/bench.elf.
# LR=1 sh ... adds sotto 1200 at 8 kHz (encoder and decoder) and also links lr.elf, which holds
# nothing else (run.py --lr IN.raw, or --lr IN.bit for the decoder alone; its flash count is
# sotto 1200's alone).
# LR16=k6|full sh ... builds v3.8 with sotto 1200 hiss at 16 kHz as well (run.py --lr16 on lr16.elf;
# --lr on lr.elf, the same objects): k6 is the K6 hiss layer (FX_HISS_LIGHT + FX_HISS_FB, as
# c/Makefile's K6HISS builds it), full the v3.8 layer.
# FPU=1 sh ... builds with the OpenRTX radios' float ABI (-mfpu=fpv4-sp-d16 -mfloat-abi=hard)
# instead of soft float; run.py turns the FPU on.
# Usage: sh tools/cm4_build.sh [extra clang options, e.g. -Os or -DFX_SPLIT_MUL]
#        CM4_OUT=dir sh tools/cm4_build.sh ...
# Default -O2 (OpenRTX builds with -Os; pass -Os to see that), unaligned access on (as GCC
# does for the Cortex-M4). VARIANT=v3.6 drops the pitch third; VARIANT=v3.8 adds the 16 kHz
# hiss band (fixed/sotto_fx_hiss.c, 30 s of percentile history as on the C55x bench; run.py
# --16k times it). Needs clang and ld.lld (any recent LLVM; tested with 18) and nothing from ARM.
# SPDX-License-Identifier: MIT
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${CM4_OUT:-"$ROOT/c/fixed/cm4/build"}
CC=${CM4_CC:-clang}
LD=${CM4_LD:-ld.lld}
[ -z "$LR16" ] || VARIANT=v3.8
VFLAGS="-DSOTTO_V36"
[ "${VARIANT:-v3.7}" = v3.6 ] || VFLAGS="$VFLAGS -DSOTTO_PITCH_THIRD"
SRCS="fx_math fx_tables sotto_fx_enc sotto_fx_dec"
SYMS=""
# the roots of lr.elf and lr16.elf, one per line
LR_SYMS="
-u sotto_lr_enc_create
-u sotto_lr_encode
-u sotto_lr_encode_part
-u sotto_lr_enc_flush
-u sotto_lr_dec_create
-u sotto_lr_decode
-u sotto_lr_dec_flush
-u sotto_lr_decode_half
-u sotto_lr_dec_flush_half
"
LR16_SYMS="
-u sotto_lr_enc16_create
-u sotto_lr_encode16
-u sotto_lr_enc16_flush
-u sotto_lr_dec16_create
-u sotto_lr_decode16
-u sotto_lr_dec16_flush
-u bench_lr_dec16_delay
"
if [ -n "$LR" ] || [ -n "$LR16" ]; then
  SRCS="$SRCS sotto_fx_lr"
  SRCS="$SRCS sotto_fx_lr_enc"
  SYMS="$SYMS $LR_SYMS"
fi
if [ "${VARIANT:-v3.7}" = v3.8 ]; then
  SRCS="$SRCS sotto_fx_hiss"
  VFLAGS="$VFLAGS -DSOTTO_V38 -DFX_PCT_MAX=3000"
  SYMS="$SYMS -u sotto_enc16_create -u sotto_encode16 -u sotto_enc16_flush -u sotto_dec16_create -u sotto_decode16 -u sotto_dec16_flush"
fi
case "$LR16" in
  "") ;;
  k6)
    VFLAGS="$VFLAGS -DFX_HISS_LIGHT -DFX_HISS_FB"
    SRCS="$SRCS sotto_fx_vlr"
    EXTRA="sotto_vlr_tables" ;;
  full) ;;
  *) echo "LR16 is k6 or full" >&2; exit 1 ;;
esac
[ -z "$LR16" ] || SYMS="$SYMS $LR16_SYMS"
FLOAT="-mfloat-abi=soft"
[ -z "$FPU" ] || FLOAT="-mfpu=fpv4-sp-d16 -mfloat-abi=hard"
RES=$("$CC" -print-resource-dir)
CFLAGS="--target=thumbv7em-none-eabi -mcpu=cortex-m4 -mthumb $FLOAT -munaligned-access -nostdinc
  -isystem $ROOT/c/fixed/cm4/inc -isystem $RES/include -ffunction-sections -fdata-sections -std=c99
  -Wall -Wno-unused-function $VFLAGS -I$ROOT/c -O2 $*"
mkdir -p "$OUT"
OBJS=""
for f in $SRCS; do
  $CC $CFLAGS -c "$ROOT/c/fixed/$f.c" -o "$OUT/$f.o"
  OBJS="$OBJS $OUT/$f.o"
done
for f in $EXTRA; do
  $CC $CFLAGS -c "$ROOT/c/$f.c" -o "$OUT/$f.o"
  OBJS="$OBJS $OUT/$f.o"
done
$CC $CFLAGS -ffreestanding -fno-builtin -c "$ROOT/c/fixed/cm4/shim.c" -o "$OUT/shim.o"
$CC --target=thumbv7em-none-eabi -mcpu=cortex-m4 $FLOAT -c "$ROOT/c/fixed/cm4/divmod.s" -o "$OUT/divmod.o"
LIBS="$OUT/shim.o $OUT/divmod.o"
LDF="-T $ROOT/c/fixed/cm4/link.ld --gc-sections -u heap_used"
# shellcheck disable=SC2086
$LD $LDF -e sotto_encode -u sotto_enc_create -u sotto_enc_flush \
  -u sotto_dec_create -u sotto_decode -u sotto_dec_flush $SYMS $OBJS $LIBS -o "$OUT/bench.elf"
echo "built $OUT/bench.elf"
if [ -n "$LR" ] || [ -n "$LR16" ]; then
  # shellcheck disable=SC2086
  $LD $LDF -e sotto_lr_encode $LR_SYMS $OBJS $LIBS -o "$OUT/lr.elf"
  echo "built $OUT/lr.elf"
fi
if [ -n "$LR16" ]; then
  # shellcheck disable=SC2086
  $LD $LDF -e sotto_lr_encode16 $LR16_SYMS $OBJS $LIBS -o "$OUT/lr16.elf"
  echo "built $OUT/lr16.elf"
fi
