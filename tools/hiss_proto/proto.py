from common import *
DCT = vl.DCT

class Proto(vl.SottoV36):
    def __init__(self, uv_wo=None, uv_gain=0.0, cb5=None, oracle=False, **kw):
        super().__init__(**kw)
        self.uv_wo, self.uv_gain, self.cb5, self.oracle = uv_wo, uv_gain, cb5, oracle
        self._or = {}

    def uu_targets(self, x):
        m = vl.analyse(x, self.PITCH)
        if len(m) % 2: m = np.concatenate([m, m[-1:]])
        rk = vl.to_rate_k(m)
        return rk - rk.mean(1, keepdims=True)

    def encode(self, x):
        bits = super().encode(x)
        if self.cb5 is None and not self.oracle:
            return bits
        sh = self.uu_targets(x)
        for f in range(len(bits)):
            if bits[f, 0] or bits[f, 1]:
                continue
            t = sh[2 * f]
            if self.oracle:
                self._or[f] = t; continue
            idx = [int(''.join(map(str, bits[f, 14 + sum(self.fields[:j]):14 + sum(self.fields[:j + 1])])), 2) for j in range(len(self.fields))]
            r = ((t - self._shape_val(idx)) @ DCT.T)[1:]
            i5 = int(np.argmin(((self.cb5 - r) ** 2).sum(1)))
            bits[f, 2:9] = [(i5 >> (6 - b)) & 1 for b in range(7)]
        return bits

    def _frame_hook(self, f, vcode, wi, shape):
        if vcode == 0:
            if self.oracle and f in self._or: return self._or[f]
            if self.cb5 is not None:
                c = np.zeros(vl.K); c[1:] = self.cb5[wi]; return shape + c @ DCT
        return shape

    def _model_hook(self, m, rk, en):
        u = np.where(m['voiced'] == 0)[0]
        if self.uv_wo is not None and len(u):
            mu = vl.set_wo(m[u], np.full(len(u), self.uv_wo), np.zeros(len(u), int))
            m[u] = vl.set_energy(vl.from_rate_k(mu, rk[u]), en[u])
        if self.uv_gain:
            for k in u: m[k]['A'] *= 10 ** (self.uv_gain / 20)
        return m
