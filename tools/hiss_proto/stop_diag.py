"""Where does the 't' of 'sunlight strikes' (p095 ~1.06-1.22 s) go? Per 10 ms: original vs
v3.7 vs the v3.8 candidate, in five bands, plus the codes and the decoder's energy."""
import sys; sys.path.insert(0,'/home/claude/sotto/sim')
import numpy as np, soundfile as sf, vocoder_lab as vl, hiss_band as hb
from scipy.signal import resample_poly
vl.TRACK2['lag']=8
x=sf.read('/tmp/claude-0/hiss/clips16/ears_p095_m.wav')[0]; x=x[:len(x)//320*320]
z=np.load('/tmp/claude-0/hiss/bits/ears_p095_m.npz'); b=z['bits']
d=hb.SottoV38(vowel='speaker',vowel_shape='fine',voiced_trim=-5,blend=True,release_ms=0,keep_mixed=True)
y8=d.decode_audio16(b,None,n16=len(x))
v=vl.SottoV37(); b7=v.encode(resample_poly(x,1,2)); y7=vl.synthesise(v.decode(b7))[160:]; y7=resample_poly(np.pad(y7,(0,max(0,len(x)//2-len(y7))))[:len(x)//2],2,1)
BANDS=[(0,500),(500,1000),(1000,2000),(2000,4000),(4000,8000)]
P=lambda y: hb.bands_db(np.abs(hb.stft(y))**2,BANDS)
o,a,c=P(x),P(y7),P(y8)
code=b[:,0]*2+b[:,1]; code7=b7[:,0]*2+b7[:,1]
ei=np.array([int(''.join(map(str,r[9:14])),2) for r in b])
print('t     code7 code8 ecode | orig 0-.5 .5-1 1-2 2-4 4-8 | v3.7 | v3.8')
for t in range(96,126):
    g=t//2
    print(f"{t/100:5.2f}   {'.VMe'[code7[g]]}     {'.VMe'[code[g]]}   {ei[g]:2d}  | "+' '.join(f"{v:5.0f}" for v in o[t])+' | '+' '.join(f"{v:5.0f}" for v in a[t])+' | '+' '.join(f"{v:5.0f}" for v in c[t]))
