#!/bin/sh
# sotto 1200 on the Cortex-M4 bench (TYT MD-UV380/390), for CI and by hand: builds the bench
# (tools/cm4_build.sh), runs sotto 1200 at 8 kHz (run.py --lr) and sotto 1200 hiss at 16 kHz
# (run.py --lr16) on short clips, checks that the M4's bits and samples equal the x86 fixed-point
# tools', and prints a Markdown table of MHz, RAM and flash (also to $GITHUB_STEP_SUMMARY when set).
# Fails on any byte that differs, or on a worst 40 ms call over 168 MHz (the STM32F405's clock).
# Usage: make -C c fixed && sh tools/cm4_lr_check.sh [-O2 | -Os | other clang options]
# Env: LR16=full|k6, the 16 kHz build's hiss layer (default full, v3.8's; k6 the K6's, decoder
#      only); CLIP8 (8 kHz raw),
#      CLIP16 (16 kHz raw or .flac), BITS (sotto 1200 superframes to decode while a build's
#      encoder is a stub); FPU=1 for the hard-float build; CM4_CHECK_DIR for the work files.
# SPDX-License-Identifier: MIT
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OPT=${*:--O2}
LR16=${LR16:-full}
W=${CM4_CHECK_DIR:-"$ROOT/c/fixed/cm4/check"}
CLIP8=${CLIP8:-"$ROOT/codec/codec2/raw/hts1a.raw"}
CLIP16=${CLIP16:-"$ROOT/docs/course/audio/hiss_original.flac"}
BITS=${BITS:-"$ROOT/docs/samples/rates/female_libri198_14s__1200.bit"}
RUN="python3 $ROOT/c/fixed/cm4/run.py"
X86="$ROOT/c/fixed"
mkdir -p "$W"
case "$CLIP16" in
  *.flac)
    if command -v flac >/dev/null; then
      flac -s -d -f --force-raw-format --endian=little --sign=signed -o "$W/clip16.raw" "$CLIP16"
    else
      ffmpeg -v error -y -i "$CLIP16" -f s16le -acodec pcm_s16le "$W/clip16.raw"
    fi
    CLIP16="$W/clip16.raw" ;;
esac

# one build when the 16 kHz layer is the full one (its 8 kHz decoder is the plain v3.8 one);
# with the K6 layer, whose 8 kHz decoder reads the hiss fields its own way, a second plain build
# for the 8 kHz mode
# shellcheck disable=SC2086
CM4_OUT="$W/b16" LR16=$LR16 sh "$ROOT/tools/cm4_build.sh" $OPT >/dev/null
if [ "$LR16" = full ]; then
  ELF8="$W/b16/lr.elf"
else
  # shellcheck disable=SC2086
  CM4_OUT="$W/b8" VARIANT=v3.8 LR=1 sh "$ROOT/tools/cm4_build.sh" $OPT >/dev/null
  ELF8="$W/b8/lr.elf"
fi
DEC16="$X86/sotto_dec_fx"
[ "$LR16" = full ] || DEC16="$X86/sotto_dec_fx_k6"

fail=0
# mode: lr (8 kHz) or lr16; then the M4 build, the clip, the x86 tools' rate options
check() {
  mode=$1 elf=$2 clip=$3 opts=$4 dec=$5
  # shellcheck disable=SC2086
  if "$X86/sotto_enc_fx" $opts "$clip" "$W/$mode.x86.bit" 2>/dev/null; then
    $RUN "$elf" "$clip" --$mode --bits "$W/$mode.m4.bit" --pcm "$W/$mode.m4.raw" --json "$W/$mode.json" >/dev/null
    if cmp "$W/$mode.x86.bit" "$W/$mode.m4.bit"; then
      echo "$mode: encoder bits equal the x86 build's ($(wc -c <"$W/$mode.m4.bit") bytes)"
    else
      fail=1
    fi
    src="$W/$mode.x86.bit"
  else
    echo "$mode: no fixed-point encoder in this tree yet; decoding $(basename "$BITS")"
    $RUN "$elf" "$clip" --$mode --dec-bits "$BITS" --pcm "$W/$mode.m4.raw" --json "$W/$mode.json" >/dev/null
    src="$BITS"
  fi
  # shellcheck disable=SC2086
  "$dec" $opts "$src" "$W/$mode.x86.raw"
  if cmp "$W/$mode.x86.raw" "$W/$mode.m4.raw"; then
    echo "$mode: decoder samples equal the x86 build's ($(wc -c <"$W/$mode.m4.raw") bytes)"
  else
    fail=1
  fi
}
check lr "$ELF8" "$CLIP8" "-1200" "$X86/sotto_dec_fx"
check lr16 "$W/b16/lr16.elf" "$CLIP16" "-16 -1200" "$DEC16"

python3 - "$W/lr.json" "$W/lr16.json" "$OPT" "$LR16" "${FPU:+hard float}" >"$W/table.md" <<'EOF'
import json, sys
opt, layer, fpu = sys.argv[3], sys.argv[4], sys.argv[5] or 'soft float'
print(f'### sotto 1200 on the Cortex-M4 bench ({opt}, {fpu}, 16 kHz hiss layer: {layer})\n')
print('MHz for real time at zero wait states (mean / worst 40 ms call); bytes.\n')
print('| Mode | Encoder MHz | Decoder MHz | Encoder state | Decoder state | Stack enc / dec | Static RAM | Flash |')
print('|---|---:|---:|---:|---:|---:|---:|---:|')
over = False
for p in sys.argv[1:3]:
    j = json.load(open(p))
    def m(k):
        global over
        if k not in j:
            return 'none yet'
        over = over or j[k]['worst'] > 168
        return f"{j[k]['mean']} / {j[k]['worst']}"
    print(f"| {j['mode']} | {m('encoder_MHz')} | {m('decoder_MHz')} | {j.get('encoder_state_bytes', '-')} | "
          f"{j['decoder_state_bytes']} | {j.get('encoder_stack_bytes', '-')} / {j['decoder_stack_bytes']} | "
          f"{j['static_ram_bytes']} | {j['flash_bytes']} |")
print('\nOVER 168 MHz' if over else '\nWorst calls within 168 MHz.')
EOF
cat "$W/table.md"
[ -z "$GITHUB_STEP_SUMMARY" ] || cat "$W/table.md" >>"$GITHUB_STEP_SUMMARY"
if grep -q "OVER 168" "$W/table.md"; then
  fail=1
fi
exit $fail
