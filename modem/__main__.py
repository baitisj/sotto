"""sotto softmodem command line.

  python -m modem tx voice.bit out.wav          Codec 2 2400 bits -> baseband audio
  python -m modem rx in.wav voice.bit           baseband audio -> Codec 2 2400 bits
  python -m modem tx voice.bit out.cf32 --iq 240000   ... or FM-modulated IQ for an SDR
  python -m modem rx in.cf32 voice.bit --iq 240000    ... or IQ from an SDR

Audio is the radio's 9600 (flat) data port signal: TX audio drives the modulator directly,
RX audio is the discriminator output. Levels, polarity and DC are found automatically.
Make and play the .bit files with Codec 2's c2enc/c2dec at 2400 bit/s.
"""
import argparse
import sys
import numpy as np
import soundfile as sf

from . import c4fm, sdr
from .link import Transmitter, Receiver
from .payload import NB, SCHEMES


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m modem", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("tx", "rx"):
        p = sub.add_parser(name)
        p.add_argument("input")
        p.add_argument("output")
        p.add_argument("--scheme", default="sotto_vw", choices=sorted(SCHEMES))
        p.add_argument("--iq", type=int, metavar="RATE", help="use complex64 IQ at RATE samples/s")
    t = sub.choices["tx"]
    t.add_argument("--rate", type=int, default=48000, help="audio sample rate (default 48000)")
    t.add_argument("--level", type=float, default=0.4,
                   help="audio amplitude of the outer (+-1800 Hz) symbols, 0..1 (default 0.4)")
    t.add_argument("--src", default="N0CALL")
    t.add_argument("--dest", default="CQCQCQ")
    t.add_argument("--dgid", type=int, default=0)
    r = sub.choices["rx"]
    r.add_argument("--no-conceal", action="store_true", help="pass bad frames through as decoded")
    a = ap.parse_args(argv)

    if a.cmd == "tx":
        b = np.unpackbits(np.fromfile(a.input, np.uint8))
        frames = b[:len(b) // NB * NB].reshape(-1, NB).astype(np.int8)
        tx = Transmitter(a.scheme, a.dest, a.src, a.dgid)
        f = tx.modulate(frames)
        if a.iq:
            sdr.fm_modulate(f, c4fm.FS, a.iq).tofile(a.output)
        else:
            x = np.clip(c4fm._resample(f, c4fm.FS, a.rate) / 1800.0 * a.level, -1, 1)
            sf.write(a.output, x.astype(np.float32), a.rate, subtype="PCM_16")
        print(f"{len(frames)} vocoder frames, {len(tx.frames(frames))} YSF frames", file=sys.stderr)
        return 0

    if a.iq:
        x, fs = sdr.fm_demodulate(np.fromfile(a.input, np.complex64), a.iq), c4fm.FS
    else:
        x, fs = sf.read(a.input, always_2d=True)
        x = x[:, 0]
    out = Receiver(a.scheme, fs=fs).receive(x, conceal=not a.no_conceal)
    np.packbits(out["frames"].astype(np.uint8).reshape(-1)).tofile(a.output)
    g = out["good"]
    hdr = out["header"]
    print(f"{len(out['rx_frames'])} YSF frames, {len(g)} vocoder frames, "
          f"{int((~g).sum())} concealed" + (f", from {hdr['src']} to {hdr['dest']}" if hdr else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
