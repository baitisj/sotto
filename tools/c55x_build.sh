#!/bin/sh
# Build the fixed-point sotto for the TI C5517 with TI's C5500 compiler (cl55, CGT 4.4.1):
# c/fixed/c55x/build/bench.out, plus the assembly listings (.asm) and the link map.
# Usage: C55X_CGT=/path/to/c5500_4.4.1 sh tools/c55x_build.sh [extra cl55 options]
#        C55X_MAIN=fxtest sh tools/c55x_build.sh   builds fxtest.out (primitive checksums)
# Run make -C c fixed first, for c/fixed/fx_tables.c.
# SPDX-License-Identifier: MIT
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CGT=${C55X_CGT:-/opt/ti/c5500_4.4.1/c5500_4.4.1}
MAIN=${C55X_MAIN:-bench}
OUT=${C55X_OUT:-"$ROOT/c/fixed/c55x/build"}
mkdir -p "$OUT"
cd "$OUT"
# -vcpu:3.3: the C5517's CPU revision; large memory model; --gcc for aggregate initialisers
# that aren't constant; -k keeps the assembly
OPTS="-vcpu:3.3 --memory_model=large -O3 --gcc -k -DSOTTO_PITCH_THIRD -I$CGT/include -I$ROOT/c $*"
for f in fx_math fx_tables sotto_fx_enc sotto_fx_dec; do
  "$CGT/bin/cl55" $OPTS --diag_suppress=1173 -c "$ROOT/c/fixed/$f.c"
done
"$CGT/bin/cl55" $OPTS -c "$ROOT/c/fixed/c55x/$MAIN.c"
"$CGT/bin/cl55" $OPTS -z --rom_model --stack_size=0x2000 --sys_stacksize=0x1000 --heap_size=0x8000 -o $MAIN.out -m $MAIN.map -i"$CGT/lib" \
  $MAIN.obj fx_math.obj fx_tables.obj sotto_fx_enc.obj sotto_fx_dec.obj \
  "$ROOT/c/fixed/c55x/bench.cmd" -lrts55x.lib
echo "built $OUT/$MAIN.out"
