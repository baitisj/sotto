"""Postfilter strength on unvoiced frames (decoder only, cached v7 bits): PESQ-NB, and the
200-1200 Hz envelope deficit in the 'strikes' burst/s (p095 1.14-1.22 s)."""
import sys, glob, os; sys.path.insert(0,'/home/claude/sotto/sim')
import numpy as np, soundfile as sf, vocoder_lab as vl, hiss_band as hb
from scipy.signal import resample_poly
from pesq import pesq
vl.TRACK2['lag']=8
PFS=[None,1.2,1.1,1.0]
res={p:[] for p in PFS}
for c in sorted(glob.glob('/tmp/claude-0/hiss/clips16/*.wav')):
    k=os.path.basename(c)[:-4]; x=sf.read(c)[0]; x=x[:len(x)//320*320]; x8=resample_poly(x,1,2)
    b=np.load(f'/tmp/claude-0/hiss/bits/{k}.npz')['bits']; row=[]
    for p in PFS:
        m=hb.SottoV38(uv_pf=p).decode(b); y=vl.synthesise(m)[vl.ar.CODEC_DELAY:]; n=min(len(y),len(x8))
        res[p].append(pesq(8000,x8[:n],y[:n],'nb')); row.append(res[p][-1])
        if k=='ears_p095_m':
            rk=vl.to_rate_k(m); mo=vl.analyse(x8,vl.SottoV37.PITCH); ro=vl.to_rate_k(mo)
            print(f"  uv_pf {p}: 200-1200 Hz deficit over 1.14-1.22 s: {np.mean(ro[114:123,:6]-rk[114:123,:6]):.1f} dB; 2-4 kHz: {np.mean(ro[114:123,10:]-rk[114:123,10:]):.1f} dB")
    print(f"{k:22s} "+' '.join(f"{v:.3f}" for v in row),flush=True)
print('mean:', ' '.join(f"{p}: {np.mean(v):.3f}" for p,v in res.items()))
