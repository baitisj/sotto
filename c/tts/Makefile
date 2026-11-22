# sotto-tts in C (docs/sotto-tts.md): text -> sotto 1200 superframes on the K6's fixed-point
# coder. `make` builds sotto_tts (the command line tool); `make data` rewrites sotto_tts_data.c
# from tts/ (python3); the web page's module is built in ../wasm (make sotto_tts.wasm).
# Plain v3.7 core (no SOTTO_V38): what the K6 plays.
CC ?= cc
CFLAGS ?= -O2 -std=gnu99 -Wall -Wno-unused-function
DEFS = -DSOTTO_V36 -DSOTTO_PITCH_THIRD
SRCS = sotto_tts.c \
       sotto_tts_data.c \
       ../fixed/fx_math.c \
       ../fixed/fx_tables.c \
       ../fixed/sotto_fx_enc.c \
       ../fixed/sotto_fx_lr_enc.c \
       ../fixed/sotto_fx_vlr.c \
       ../fixed/sotto_fx_dec.c \
       ../fixed/sotto_fx_lr.c \
       ../sotto_vlr_tables.c

all: sotto_tts

sotto_tts: tts_cli.c $(SRCS) sotto_tts.h
	$(CC) $(CFLAGS) $(DEFS) -I.. -I../fixed -o $@ tts_cli.c $(SRCS) -lm

data:
	cd ../.. && python3 tools/tts_cdata.py

clean:
	rm -f sotto_tts
.PHONY: all data clean
