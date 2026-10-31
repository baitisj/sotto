# sotto C port. Links Codec 2 (LGPL-2.1) built in ../build/codec2 from ../codec/codec2.
#   make                 libsotto.so, libsotto.a, sotto_enc and sotto_dec
#   make check           API test against the shared library
#   make install PREFIX=/usr/local   library, header and pkg-config file
#   make CODEC2_SRC=... CODEC2_LIB=...   to use another Codec 2 tree
#   make clean all CODEBOOK=sim/data/shape_msvq_9988.npz   for another codebook
CODEC2_SRC ?= ../codec/codec2/src
CODEC2_LIB ?= ../build/codec2/src
PYTHON ?= python3
CODEBOOK ?= sim/data/shape_msvq_34.npz
PREFIX ?= /usr/local
LIBDIR ?= $(PREFIX)/lib
INCDIR ?= $(PREFIX)/include

MAJOR = 0
VERSION = 0.1.0
SONAME = libsotto.so.$(MAJOR)

CFLAGS ?= -O2 -g -Wall -Wextra -Wno-unused-parameter
CFLAGS += -std=c99 -ffp-contract=off -fPIC -fvisibility=hidden -I$(CODEC2_SRC) -I$(CODEC2_LIB)/.. -I.
# the build-tree Codec 2 is found through an rpath; installed copies use the system path
C2LIBS = -L$(CODEC2_LIB) -Wl,-rpath,$(abspath $(CODEC2_LIB)) -lcodec2 -lm

all: libsotto.so libsotto.a sotto_enc sotto_dec

sotto_codebook.c: ../$(CODEBOOK) ../tools/export_codebook_c.py
	cd .. && $(PYTHON) tools/export_codebook_c.py $(CODEBOOK) c/sotto_codebook.c

sotto.o: sotto.c sotto.h sotto_codebook.h
sotto_codebook.o: sotto_codebook.c sotto_codebook.h

libsotto.a: sotto.o sotto_codebook.o
	$(AR) rcs $@ $^

libsotto.so.$(VERSION): sotto.o sotto_codebook.o
	$(CC) -shared -Wl,-soname,$(SONAME) -o $@ $^ $(C2LIBS)
libsotto.so: libsotto.so.$(VERSION)
	ln -sf $< $(SONAME)
	ln -sf $< $@

sotto_enc: sotto_enc.o libsotto.a
	$(CC) -o $@ $^ $(C2LIBS)
sotto_dec: sotto_dec.o libsotto.a
	$(CC) -o $@ $^ $(C2LIBS)

test_api: test_api.o libsotto.so
	$(CC) -o $@ test_api.o -L. -Wl,-rpath,$(abspath .) -lsotto -lm

check: test_api
	./test_api
	@exported=$$(nm -D --defined-only libsotto.so | awk '$$2 == "T" || $$2 == "D" || $$2 == "R" {print $$3}' | grep -v '^sotto_' || true); \
	if [ -n "$$exported" ]; then echo "unexpected exports: $$exported"; exit 1; fi; \
	echo "exports: only sotto_*"

sotto.pc: sotto.pc.in
	sed -e 's|@PREFIX@|$(PREFIX)|' -e 's|@LIBDIR@|$(LIBDIR)|' -e 's|@INCDIR@|$(INCDIR)|' \
	    -e 's|@VERSION@|$(VERSION)|' $< > $@

install: libsotto.so libsotto.a sotto.pc
	install -d $(DESTDIR)$(LIBDIR)/pkgconfig $(DESTDIR)$(INCDIR)
	install -m 755 libsotto.so.$(VERSION) $(DESTDIR)$(LIBDIR)/
	ln -sf libsotto.so.$(VERSION) $(DESTDIR)$(LIBDIR)/$(SONAME)
	ln -sf libsotto.so.$(VERSION) $(DESTDIR)$(LIBDIR)/libsotto.so
	install -m 644 libsotto.a $(DESTDIR)$(LIBDIR)/
	install -m 644 sotto.h $(DESTDIR)$(INCDIR)/
	install -m 644 sotto.pc $(DESTDIR)$(LIBDIR)/pkgconfig/

clean:
	rm -f *.o libsotto.a libsotto.so* sotto_enc sotto_dec test_api sotto_codebook.c sotto.pc

.PHONY: all check install clean
