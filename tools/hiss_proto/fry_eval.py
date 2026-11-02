"""Fry rule (steady pitch through jumpy voiced stretches, sent as mixed): frames changed,
PESQ-NB on the 12 test clips, and the pitch track in the two creaky spots Jeff flagged."""
import sys; sys.path.insert(0,'/home/claude/sotto/sim')
import numpy as np, soundfile as sf, vocoder_lab as vl, hiss_band as hb, glob, os
from scipy.signal import resample_poly
from pesq import pesq
vl.TRACK2['lag']=8
SPOT={'ears_p095_m':(4.20,4.50),'ears_p051_f':(6.10,6.46)}
base=dict(whisper=True,vsmooth=True,sib_db=3.0)
tot=[]
for c in sorted(glob.glob('/tmp/claude-0/hiss/clips16/*.wav')):
    k=os.path.basename(c)[:-4]; x=sf.read(c)[0]; x=x[:len(x)//320*320]; x8=resample_poly(x,1,2); r=[]; B=[]
    for kw in (base, dict(base,fry='slew')):
        b,_,_=hb.SottoV38(**kw).encode_low(x); B.append(b)
        y=vl.synthesise(hb.SottoV38().decode(b))[vl.ar.CODEC_DELAY:]; n=min(len(y),len(x8)); r.append(pesq(8000,x8[:n],y[:n],'nb'))
    tot.append(r); ch=np.mean((B[0]!=B[1]).any(1))*100
    print(f"{k:22s} changed {ch:4.1f}%  PESQ {r[0]:.3f} -> {r[1]:.3f}",flush=True)
    if k in SPOT:
        a,e=SPOT[k]
        for b,nm in zip(B,('before','after')):
            m=hb.SottoV38().decode(b); wo=m['Wo']*4000/np.pi; code=b[:,0]*2+b[:,1]
            print('   ',nm,' '.join(f"{'.VMe'[code[g]]}{wo[2*g]:.0f}" for g in range(int(a*50),int(e*50))))
print('mean PESQ %.3f -> %.3f'%tuple(np.mean(tot,0)))
