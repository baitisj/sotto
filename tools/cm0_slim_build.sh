#!/bin/sh
# Build the slim sotto 1200 encoder (c/fixed/sotto_fx_slim.c, docs/sotto-slim.md) for a
# Cortex-M0 with clang and lld, bare metal, for the cycle bench in c/fixed/cm0/run_slim.py:
# c/fixed/cm0/build-slim/slim.elf. The image holds the shape codebook too (30,720 B of
# fx_tables.c); on the K6 that is in SPI flash.
# Usage: sh tools/cm0_slim_build.sh [extra clang options, e.g. -Oz or -DSLIM_FULL_SEARCH]
#        CM0_OUT=dir sh tools/cm0_slim_build.sh ...
# Needs clang and ld.lld (tested with 18).
# SPDX-License-Identifier: MIT
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${CM0_OUT:-"$ROOT/c/fixed/cm0/build-slim"}
CC=${CM0_CC:-clang}
LD=${CM0_LD:-ld.lld}
RES=$("$CC" -print-resource-dir)
CFLAGS="--target=thumbv6m-none-eabi -mcpu=cortex-m0 -mthumb -mfloat-abi=soft -nostdinc
  -isystem $ROOT/c/fixed/cm4/inc -isystem $RES/include -ffunction-sections -fdata-sections -std=c99
  -Wall -Wno-unused-function -DSOTTO_V36 -DSOTTO_PITCH_THIRD -DFX_NARROW_MUL -I$ROOT/c -O2 $*"
mkdir -p "$OUT"
OBJS=""
for f in sotto_fx_slim fx_tables; do
  "$CC" $CFLAGS -c "$ROOT/c/fixed/$f.c" -o "$OUT/$f.o"
  OBJS="$OBJS $OUT/$f.o"
done
"$CC" $CFLAGS -ffreestanding -fno-builtin -c "$ROOT/c/fixed/cm4/shim.c" -o "$OUT/shim.o"
"$CC" $CFLAGS -ffreestanding -fno-builtin -c "$ROOT/c/fixed/cm0/rt.c" -o "$OUT/rt.o"
"$CC" --target=thumbv6m-none-eabi -mcpu=cortex-m0 -c "$ROOT/c/fixed/cm0/divmod.s" -o "$OUT/divmod.o"
"$LD" -T "$ROOT/c/fixed/cm4/link.ld" --gc-sections -e slim_encode10 \
  -u slim_enc_bytes \
  -u slim_enc_init \
  -u slim_encode10 \
  -u slim_flush \
  $OBJS "$OUT/shim.o" "$OUT/rt.o" "$OUT/divmod.o" -o "$OUT/slim.elf"
llvm-size "$OUT/slim.elf" 2>/dev/null || true
echo "built $OUT/slim.elf"
