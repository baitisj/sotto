"""Write 16-bit FLAC, with HamFLAC (github.com/baitisj/hamflac) when it is available.

Set HAMFLAC to the hamflac binary to use it; otherwise soundfile (libFLAC) writes the file.
Either way the result is ordinary FLAC that any decoder reads.
"""
import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf

HAMFLAC = os.environ.get("HAMFLAC") or shutil.which("hamflac")


def write_flac(path, x, fs):
    x16 = np.clip(np.round(np.asarray(x, float) * 32767), -32768, 32767).astype(np.int16)
    if not HAMFLAC:
        sf.write(path, x16, fs, subtype="PCM_16")
        return
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "in.wav")
        sf.write(wav, x16, fs, subtype="PCM_16")
        subprocess.run([HAMFLAC, "encode", wav, path, "--no-sync"], check=True,
                       stdout=subprocess.DEVNULL)
