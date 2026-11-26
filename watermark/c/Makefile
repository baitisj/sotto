# C port of the harmonic phase watermark (wm.c) and its WebAssembly build for docs/watermark.html.
#   make            build/libwm_core.so: sender, receiver, ID frame, FM channel (no pitch tracker;
#                   python watermark/check_c.py compares it with the Python prototype)
#   make full       build/libwm.so: the same plus sotto's encoder pitch tracker (wm_track.c);
#                   run `make` in the repository root first (libsotto.a, build/codec2)
#   make wasm       build/watermark.wasm (clang, wasm-ld and a wasm32-wasi sysroot, as c/wasm)
#   make install    copies it to docs/watermark.wasm, the file the page loads
#   make tables     rewrites wm_tables.h (numpy, scipy);  make check-tables fails if it is stale
ROOT = ../..
PYTHON ?= python3
CC ?= cc
CFLAGS ?= -O2 -std=gnu99 -fPIC -Wall
C2SRC = $(ROOT)/codec/codec2/src
C2GEN = $(ROOT)/build/codec2
SOTTO_DEFS = -DSOTTO_V36 -DSOTTO_PITCH_THIRD -DSOTTO_V38

all: build/libwm_core.so

build:
	mkdir -p build

build/libwm_core.so: wm.c wm.h wm_tables.h | build
	$(CC) $(CFLAGS) -shared -o $@ wm.c -lm

full: build/libwm.so
build/libwm.so: wm.c wm_track.c wm.h wm_tables.h | build
	$(CC) $(CFLAGS) $(SOTTO_DEFS) -I$(ROOT)/c -shared -o $@ wm.c wm_track.c \
	  $(ROOT)/c/libsotto.a -L$(C2GEN)/src -Wl,-rpath,$(abspath $(C2GEN)/src) -lcodec2 -lm

# --- WebAssembly: wm.c, wm_track.c and sotto's encoder (c/sotto.c with the Codec 2 analysis it
# calls); --gc-sections drops the rest
CC_WASM ?= clang
WASI_SYSROOT ?=
TARGET = --target=wasm32-wasi $(if $(WASI_SYSROOT),--sysroot=$(WASI_SYSROOT))
WCFLAGS = $(TARGET) -O2 -std=gnu99 -ffp-contract=off -ffunction-sections -fdata-sections \
          $(SOTTO_DEFS) -I. -I$(ROOT)/c -I$(C2SRC) -I$(C2GEN) -I$(C2GEN)/codec2 -w
C2FILES = codec2.c codec2_fft.c kiss_fft.c kiss_fftr.c sine.c nlp.c phase.c postfilter.c \
          quantise.c lpc.c lsp.c interp.c newamp1.c mbest.c pack.c
C2GENFILES = codebook.c codebookd.c codebookjmv.c codebookge.c codebooknewamp1.c \
             codebooknewamp1_energy.c codebooknewamp2.c codebooknewamp2_energy.c
WSRCS = wm_wasm.c wm.c wm_track.c $(ROOT)/c/sotto.c $(ROOT)/c/sotto_codebook.c \
        $(addprefix $(C2SRC)/,$(C2FILES)) $(addprefix $(C2GEN)/src/,$(C2GENFILES))
WOBJS = $(patsubst %.c,build/wobj/%.o,$(notdir $(WSRCS)))
vpath %.c . $(ROOT)/c $(C2SRC) $(C2GEN)/src

wasm: build/watermark.wasm
build/watermark.wasm: $(WOBJS)
	$(CC_WASM) $(TARGET) -mexec-model=reactor -Wl,--gc-sections -Wl,--strip-all \
	  -Wl,-z,stack-size=1048576 -Wl,--initial-memory=16777216 -Wl,--max-memory=1073741824 \
	  -o $@ $(WOBJS)

build/wobj/%.o: %.c wm.h wm_tables.h | build/wobj
	$(CC_WASM) $(WCFLAGS) -c -o $@ $<
build/wobj:
	mkdir -p $@

install: build/watermark.wasm
	cp $< $(ROOT)/docs/watermark.wasm

tables:
	$(PYTHON) gen_tables.py > wm_tables.h
check-tables:
	$(PYTHON) gen_tables.py --check

clean:
	rm -rf build

.PHONY: all full wasm install tables check-tables clean
