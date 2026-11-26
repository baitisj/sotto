"""The C port (watermark/c/wm.c) against this Python prototype, with no codec build: the
synthetic vowel of selftest.py with its known pitch track is marked by both, read by both
receivers and decoded by both, and the C FM channel is checked to carry the ID.

make -C watermark/c && python watermark/check_c.py [--full]
--full also loads build/libwm.so (sotto's pitch tracker, `make full`) and runs a speech clip.
"""
import ctypes as C, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harmonic as hm, fmchan as fc, fec, selftest

DP = np.ctypeslib.ndpointer(np.float64, flags="C")
BP = np.ctypeslib.ndpointer(np.uint8, flags="C")


class Params(C.Structure):
    _fields_ = [("lo", C.c_double), ("hi", C.c_double), ("nsub", C.c_int), ("strength", C.c_double)]


class Code(C.Structure):
    _fields_ = [("msg", C.c_ubyte * 56), ("cw", C.c_ubyte * 124), ("nsub", C.c_int)]


class Frame(C.Structure):
    _fields_ = [("call", C.c_char * 8), ("code", C.c_int), ("start", C.c_int), ("quality", C.c_double)]


def load(name):
    lib = C.CDLL(os.path.join(HERE, "c", "build", name))
    lib.wm_embed.argtypes = [C.POINTER(Params), DP, C.c_int, DP, BP, C.POINTER(Code), DP, BP]
    lib.wm_rx_create.argtypes = [C.POINTER(Params), DP, C.c_int, DP, BP]
    lib.wm_rx_create.restype = C.c_void_p
    lib.wm_rx_read.argtypes = [C.c_void_p, C.c_int, DP, C.POINTER(C.c_int)]
    lib.wm_rx_destroy.argtypes = [C.c_void_p]
    lib.wm_decode.argtypes = [DP, C.c_int, C.c_int, C.POINTER(Frame), C.POINTER(C.c_double), C.c_void_p]
    lib.wm_channel.argtypes = [DP, C.c_int, C.c_int, C.c_double, C.c_double, C.c_double, C.c_uint, DP]
    if hasattr(lib, "wm_pitch_track"):
        for f in (lib.wm_pitch_track, lib.wm_tx_track):
            f.argtypes = [DP, C.c_int, DP, BP]
    return lib


def params(p):
    q = Params(p.band[0], p.band[1], p.nsub, p.strength)
    return C.byref(q), q


def c_code(lib, call="AG7EW", code=0x5A, nsub=4):
    c = Code()
    lib.wm_code_init(C.byref(c), call.encode(), code, nsub)
    return c


def c_embed(lib, x, track, p, code):
    f0, v = np.ascontiguousarray(track[0], float), np.ascontiguousarray(track[1], np.uint8)
    y = np.zeros(len(x))
    used = np.zeros(len(x) // hm.FS * 0 + len(x) // p.slot + 1, np.uint8)
    pp, _keep = params(p)
    lib.wm_embed(pp, np.ascontiguousarray(x, float), len(x), f0, v, C.byref(code), y, used)
    return y, used[:len(x) // p.slot].astype(bool)


def c_read(lib, z, track, p, upto=None):
    f0, v = np.ascontiguousarray(track[0], float), np.ascontiguousarray(track[1], np.uint8)
    pp, _keep = params(p)
    rx = lib.wm_rx_create(pp, np.ascontiguousarray(z, float), len(z), f0, v)
    R = np.zeros((len(z) // p.slot + 1) * p.nsub)
    off = C.c_int()
    m = lib.wm_rx_read(rx, upto or len(z), R, C.byref(off))
    lib.wm_rx_destroy(rx)
    return R[:m * p.nsub].reshape(m, p.nsub), off.value


def c_decode(lib, R, nsub):
    f, cov = Frame(), C.c_double()
    ok = lib.wm_decode(np.ascontiguousarray(R, float).ravel(), len(R), nsub, C.byref(f), C.byref(cov), None)
    return (f.call.decode(), f.code, f.start, round(f.quality, 3)) if ok else None


def c_channel(lib, x, kind, cnr_in=25, cnr_out=25, drive=0.0, seed=1):
    k = {"clean": 0, "bandpass": 1, "simplex": 2, "repeater": 3}[kind]
    y = np.zeros(len(x))
    lib.wm_channel(np.ascontiguousarray(x, float), len(x), k, cnr_in, cnr_out, drive, seed, y)
    return y


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    return bool(cond)


def core(lib):
    ok = True
    x, track = selftest.vowel()
    p = hm.Params()
    code = fec.Code(nsub=p.nsub)
    cc = c_code(lib)
    ok &= check(list(cc.cw) == list(code.cw), "codeword and whitening match fec.Code")
    j = 17
    cb = (C.c_ubyte * 4)()
    lib.wm_bits_for_slot(C.byref(cc), j, cb)
    ok &= check(list(cb) == code.bits_for_slot(j), "bits_for_slot")
    y, info = hm.embed(x, code.bits_for_slot, p, track)
    yc, used = c_embed(lib, x, track, p, cc)
    d = np.max(np.abs(y - yc)) / np.max(np.abs(y))
    ok &= check(d < 1e-6 and (used == info["slots"]).all(), f"embed matches harmonic.embed (max diff {d:.1e})")
    z = fc.bandpass if False else None
    z, _ = fc.channel(y, "repeater", cnr_in=25, cnr_out=25)
    R, est = hm.Receiver(z, p, track).read()
    Rc, off = c_read(lib, z, track, p)
    n = min(len(R), len(Rc))
    d = np.max(np.abs(R[:n] - Rc[:n])) / (np.max(np.abs(R)) + 1e-30)
    ok &= check(off == est["offset"] and len(R) == len(Rc) and d < 1e-6,
                f"receiver matches Receiver.read (offset {off}, max diff {d:.1e})")
    got, gotc = code.decode(R), c_decode(lib, Rc, p.nsub)
    ok &= check(gotc is not None and got is not None and gotc == got, f"decode {gotc} = {got}")
    # the C channel carries the ID; unmarked audio stays silent
    zc = c_channel(lib, yc, "repeater")
    g = c_decode(lib, c_read(lib, zc, track, p)[0], p.nsub)
    ok &= check(g is not None and g[:2] == ("AG7EW", 0x5A), f"C repeater 25 dB: {g}")
    zc = c_channel(lib, x, "repeater")
    ok &= check(c_decode(lib, c_read(lib, zc, track, p)[0], p.nsub) is None, "unmarked through the C repeater: no ID")
    # the C channel's level and noise against fmchan's
    for kind, a, b in (("repeater", 25, 25), ("simplex", 15, 15)):
        zp, _ = fc.channel(x, kind, cnr_in=a, cnr_out=b)
        zq = c_channel(lib, x, kind, a, b)
        e1 = np.sqrt(np.mean((zp - fc.channel(x, "bandpass")[0]) ** 2))
        e2 = np.sqrt(np.mean((zq - fc.channel(x, "bandpass")[0]) ** 2))
        ok &= check(0.6 < e2 / e1 < 1.6, f"C {kind} {a} dB distortion vs fmchan: ratio {e2 / e1:.2f}")
    return ok


def full(lib, clip):
    import soundfile as sf
    ok = True
    x, fs = sf.read(clip)
    assert fs == hm.FS
    f0p, vp = hm.pitch_track(x)
    f0c, vc = np.zeros(len(x)), np.zeros(len(x), np.uint8)
    lib.wm_pitch_track(np.ascontiguousarray(x), len(x), f0c, vc)
    both = vp & (vc > 0)
    agree = np.mean(np.abs(np.log(f0c[both] / f0p[both])) < 0.05)
    print(f"     pitch: voiced Python {vp.mean():.2f} C {vc.mean():.2f}, both {both.mean():.2f}, "
          f"within 5% where both voiced {agree:.3f}")
    ok &= check(agree > 0.9, "C pitch track agrees with tracked4")
    p = hm.Params()
    cc, code = c_code(lib), fec.Code(nsub=p.nsub)
    ft, vt = np.zeros(len(x)), np.zeros(len(x), np.uint8)
    lib.wm_tx_track(np.ascontiguousarray(x), len(x), ft, vt)
    y, used = c_embed(lib, x, (ft, vt), p, cc)
    for kind, a, b in (("bandpass", 0, 0), ("repeater", 40, 40), ("repeater", 25, 25)):
        z = c_channel(lib, y, kind, a, b)
        rt = (np.zeros(len(z)), np.zeros(len(z), np.uint8))
        lib.wm_pitch_track(np.ascontiguousarray(z), len(z), *rt)
        Rc, _ = c_read(lib, z, rt, p)
        g = c_decode(lib, Rc, p.nsub)
        # and the Python receiver on the C-marked audio
        gp = code.decode(hm.Receiver(z, p).read()[0])
        ok &= check(g is not None and g[:2] == ("AG7EW", 0x5A), f"C mark, C rx, {kind} {a}: {g}; Python rx: {gp}")
    return ok


def main():
    ok = core(load("libwm_core.so"))
    if "--full" in sys.argv:
        clip = sys.argv[sys.argv.index("--full") + 1] if len(sys.argv) > sys.argv.index("--full") + 1 else None
        ok &= full(load("libwm.so"), clip)
    print("all ok" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
