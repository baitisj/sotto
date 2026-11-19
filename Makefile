# sotto top-level build. Builds our Codec 2 fork, then libsotto and its tools in c/.
#   make                          Codec 2 (build/codec2) + libsotto.so, libsotto.a, c/sotto_enc, c/sotto_dec
#   make fixed                    the fixed-point (integer-only) encoder and decoder in c/fixed/
#   make check                    C API test, the generated-table check, the v3.7 build, then the Python tests (pytest)
#   make c37                      a VARIANT=v3.7 copy of c/ in build/c37 (all + fixed): the 8 kHz core the K6
#                                 plays, which tests/test_lr.py, test_vlr.py and test_vocoder.py check against
#   make tables                   regenerate the committed C tables from sim/data/*.npz (numpy, scipy)
#   make check-tables             fail if the committed C tables differ from what the generators write
#   make install PREFIX=/usr/local   libsotto + header + pkg-config, and libcodec2 from our fork
#   make clean                    remove the C build;  make distclean also removes build/codec2
# Variables go through to c/Makefile: VARIANT=v3.5, CODEBOOK=..., PREFIX, LIBDIR, INCDIR, DESTDIR.
# The default build needs no Python: the generated C tables are committed. PYTHON=.venv/bin/python
# picks the Python for make tables, make check-tables, make check and the VARIANT=v3.5 codebook.
PREFIX ?= /usr/local
PYTHON ?= python3
CODEC2_LIB = build/codec2/src/libcodec2.so

all: lib

codec2: $(CODEC2_LIB)
$(CODEC2_LIB):
	sh tools/build_codec2.sh

lib: $(CODEC2_LIB)
	$(MAKE) -C c

fixed: lib
	$(MAKE) -C c fixed

# c/ is v3.8; the plain (K6) codecs run on the v3.7 core, so they are checked in a v3.7 copy.
# Only sources are copied: c/'s objects are v3.8 ones. cp -p keeps the times, so it rebuilds
# only what changed.
C37 = build/c37
c37: $(CODEC2_LIB)
	mkdir -p $(C37)/fixed
	cp -p c/*.c c/*.h c/*.inc c/Makefile $(C37)/
	cp -p c/fixed/*.c c/fixed/*.h c/fixed/*.inc $(C37)/fixed/
	$(MAKE) -C $(C37) VARIANT=v3.7 CODEC2_SRC=$(CURDIR)/codec/codec2/src CODEC2_LIB=$(CURDIR)/build/codec2/src all fixed

check: lib fixed c37
	$(MAKE) -C c check
	$(MAKE) -C c check-tables PYTHON=$(PYTHON)
	$(PYTHON) -m pytest -q tests

tables check-tables:
	$(MAKE) -C c $@ PYTHON=$(PYTHON)

install: lib
	$(MAKE) -C c install
	DESTDIR=$(DESTDIR) cmake --install build/codec2 --prefix $(PREFIX)

clean:
	$(MAKE) -C c clean

distclean: clean
	rm -rf build/codec2

.PHONY: all codec2 lib fixed c37 check tables check-tables install clean distclean
