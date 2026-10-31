# sotto C port. Links Codec 2 (LGPL-2.1) built in ../build/codec2 from ../codec/codec2.
#   make            builds sotto_enc and sotto_dec
#   make CODEC2_SRC=... CODEC2_LIB=...   to use another Codec 2 tree
CODEC2_SRC ?= ../codec/codec2/src
CODEC2_LIB ?= ../build/codec2/src
PYTHON ?= python3
CFLAGS ?= -O2 -g -Wall -Wextra -Wno-unused-parameter
CFLAGS += -std=c99 -ffp-contract=off -I$(CODEC2_SRC) -I$(CODEC2_LIB)/.. -I.
LDLIBS = -L$(CODEC2_LIB) -Wl,-rpath,$(abspath $(CODEC2_LIB)) -lcodec2 -lm

all: sotto_enc sotto_dec

sotto_codebook.c: ../sim/data/shape_msvq_34.npz ../tools/export_codebook_c.py
	cd .. && $(PYTHON) tools/export_codebook_c.py sim/data/shape_msvq_34.npz c/sotto_codebook.c

libsotto.a: sotto.o sotto_codebook.o
	$(AR) rcs $@ $^

sotto.o: sotto.c sotto.h sotto_codebook.h
sotto_codebook.o: sotto_codebook.c sotto_codebook.h

sotto_enc: sotto_enc.o libsotto.a
	$(CC) -o $@ $^ $(LDLIBS)
sotto_dec: sotto_dec.o libsotto.a
	$(CC) -o $@ $^ $(LDLIBS)

clean:
	rm -f *.o libsotto.a sotto_enc sotto_dec sotto_codebook.c

.PHONY: all clean
