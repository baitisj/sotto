import numpy as np, sys
sys.path.insert(0,'.')
from c4fm_sim import *
rng=np.random.default_rng(1)
N=200000
bits=rng.integers(0,2,2*N)
lv=bits_to_levels(bits)
print("AWGN static: Eb/N0 dB -> channel BER")
for e in [4,6,8,10,12,14]:
    o=simulate(lv,e,seed=e)
    hb,_,_=soft_demod(o['y'])
    print(f"  {e:2d}  {np.mean(hb!=bits):.2e}")
# fading generator check: LCR and AFD at -10 dB for single Rayleigh
print("Rayleigh check (rho=-10 dB): fd, LCR sim/theory, AFD ms sim/theory")
for fd in [8.1,25.0]:
    h=rayleigh(4800*120,fd,np.random.default_rng(7)); p=np.abs(h)**2; p/=p.mean()
    r=np.sqrt(p); rho=10**(-10/20)
    below=r<rho; cross=np.sum(below[1:]&~below[:-1])
    T=len(r)/RS; lcr=cross/T; afd=below.mean()/lcr
    lcr_t=np.sqrt(2*np.pi)*fd*rho*np.exp(-rho**2); afd_t=(np.exp(rho**2)-1)/(rho*fd*np.sqrt(2*np.pi))
    print(f"  {fd:5.1f}  {lcr:5.2f}/{lcr_t:5.2f}  {afd*1e3:5.1f}/{afd_t*1e3:5.1f}")
