"""Stop-burst experiments on the cached v3.8 bits: an unvoiced frame that jumps >= burst_db
above the previous frame keeps its broadband shape (burst_pf) and/or gets a sharp attack
(the interpolated 10 ms subframe before it stays at the quiet level instead of ramping).
Usage: play2.py <clip>"""
import sys; sys.path.insert(0, '/home/claude/sotto/sim')
import numpy as np, soundfile as sf, vocoder_lab as vl, hiss_band as hb
from scipy.signal import resample_poly
from pesq import pesq
vl.TRACK2['lag'] = 8
clip = sys.argv[1]
x = sf.read(f'/tmp/claude-0/hiss/clips16/{clip}.wav')[0]; x = x[:len(x) // 320 * 320]; x8 = resample_poly(x, 1, 2)
b = np.load(f'/tmp/claude-0/hiss/bits/{clip}.npz')['bits']

class Play(hb.SottoV38):
    attack_db = None   # even UU subframe this far above the frame before -> sharp attack
    early = False      # the interpolated subframe takes the burst level instead of the quiet one

    def _model_hook(self, m, rk, en):
        self.n_att = 0
        if self.attack_db is not None:
            for k in range(2, len(m), 2):
                if m[k]["voiced"] == 0 and en[k] - en[k - 2] >= self.attack_db:
                    en[k - 1] = en[k] if self.early else en[k - 2]
                    m[k - 1:k] = vl.set_energy(m[k - 1:k], en[k - 1:k])
                    self.n_att += 1
        return super()._model_hook(m, rk, en)

DEC = dict(vowel='speaker', vowel_shape='fine', voiced_trim=-5, blend=True, release_ms=0, keep_mixed=True)
def sc(d):
    y = vl.synthesise(d.decode(b))[vl.ar.CODEC_DELAY:]; n = min(len(y), len(x8))
    return pesq(8000, x8[:n], y[:n], 'nb')
import os
SETS = {'1': [('base', {}), ('bpf1.0d8', dict(burst_pf=1.0, burst_db=8)), ('bpf1.0d12', dict(burst_pf=1.0, burst_db=12)),
              ('bpf1.15d8', dict(burst_pf=1.15, burst_db=8)), ('att8', dict(attack_db=8)), ('att12', dict(attack_db=12)),
              ('att8+bpf', dict(attack_db=8, burst_pf=1.0, burst_db=8))],
        '2': [('base', {}), ('att10', dict(attack_db=10)), ('att12', dict(attack_db=12)), ('att14', dict(attack_db=14)),
              ('att16', dict(attack_db=16)), ('early12', dict(attack_db=12, early=True))]}
vars_ = SETS[os.environ.get('SET', '1')]
out = []
for k, o in vars_:
    d = Play(**DEC)
    for a, val in o.items(): setattr(d, a, val)
    s = sc(d); out.append(f"{k} {s:.3f}" + (f"({d.n_att})" if d.n_att else ''))
print(f"{clip:22s} " + '  '.join(out), flush=True)
