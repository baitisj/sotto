import sys,glob,os,numpy as np,soundfile as sf
from pesq import pesq
from pystoi import stoi
d=sys.argv[1]
clips=sorted({os.path.basename(f).split('__')[0] for f in glob.glob(d+'/*__original.wav')})
codecs=['codec2_1600','codec2_2400','codec2_3200','opus_6k','opus_8k']
res={c:[] for c in codecs}
def best_align(r,x):
    n=min(len(r),len(x)); best=(-1,0)
    for lag in range(0,400,1):
        a=r[:n-lag]; b=x[lag:n]
        c=np.dot(a,b)/np.sqrt(np.dot(a,a)*np.dot(b,b)+1e-9)
        if c>best[0]: best=(c,lag)
    return best[1]
print('clip',*codecs)
for cl in clips:
    r,fs=sf.read(f'{d}/{cl}__original.wav'); row=[]
    for c in codecs:
        x,_=sf.read(f'{d}/{cl}__{c}.wav'); lag=best_align(r,x); n=min(len(r),len(x)-lag)
        rr=r[:n]; xx=x[lag:lag+n]
        p=pesq(fs,rr,xx,'nb'); s=stoi(rr,xx,fs,extended=True)
        res[c].append((p,s)); row.append(f'{p:.2f}/{s:.2f}')
    print(cl,*row)
print('MEAN',*[f'{np.mean([a for a,b in res[c]]):.2f}/{np.mean([b for a,b in res[c]]):.2f}' for c in codecs])
