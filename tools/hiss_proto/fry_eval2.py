"""Pitch slew limiter variants on cached v7 bits (features computed once per clip)."""
import sys, glob, os; sys.path.insert(0,'/home/claude/sotto/sim')
import numpy as np, soundfile as sf, vocoder_lab as vl, hiss_band as hb
from scipy.signal import resample_poly
from pesq import pesq
vl.TRACK2['lag']=8
SPOT={'ears_p095_m':(4.20,4.50),'ears_p051_f':(6.10,6.46)}
VAR=[('base',None),('s.08/8',dict(step=0.08,good_db=8)),('s.12/8',dict(step=0.12,good_db=8)),('s.08/5',dict(step=0.08,good_db=5)),('s.12/5',dict(step=0.12,good_db=5)),('s.15/6',dict(step=0.15,good_db=6))]
res={k:[] for k,_ in VAR}; chg={k:[] for k,_ in VAR}
for c in sorted(glob.glob('/tmp/claude-0/hiss/clips16/*.wav')):
    k=os.path.basename(c)[:-4]; x=sf.read(c)[0]; x=x[:len(x)//320*320]; x8=resample_poly(x,1,2)
    b0=np.load(f'/tmp/claude-0/hiss/bits/{k}.npz')['bits']; e=hb.SottoV38(); row=[]
    for nm,kw in VAR:
        b=b0.copy()
        if kw: e._slew(x8,b,**kw)
        m=hb.SottoV38().decode(b); y=vl.synthesise(m)[vl.ar.CODEC_DELAY:]; n=min(len(y),len(x8))
        res[nm].append(pesq(8000,x8[:n],y[:n],'nb')); chg[nm].append(np.mean((b!=b0).any(1))*100); row.append(f"{res[nm][-1]:.3f}/{chg[nm][-1]:.0f}%")
        if k in SPOT and nm in ('base','s.12/5','s.15/6'):
            a,e_=SPOT[k]; wo=m['Wo']*4000/np.pi; code=b[:,0]*2+b[:,1]
            print(f"   {nm:8s}",' '.join(f"{'.VMe'[code[g]]}{wo[2*g]:.0f}" for g in range(int(a*50),int(e_*50))))
    print(f"{k:22s} "+'  '.join(row),flush=True)
print('mean:', '  '.join(f"{nm}: {np.mean(res[nm]):.3f} ({np.mean(chg[nm]):.1f}% frames)" for nm,_ in VAR))
