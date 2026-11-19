"""Train sotto's shape codebook (multistage VQ) for the peak-weighted distortion that the
weighted encoder search uses (vocoder_lab.shape_weights).

Usage: python tools/train_shape_vqw.py CORPUS.npz [CORPUS2.npz ...] --out OUT.npz
         [--bits 9,9,8,8] [--joint 6] [--gamma 0.5] [--floor 40] [--unweighted]
CORPUS.npz: tools/env_corpus.py output (every 10 ms frame); the non-silent 20 ms frames
are used (frames above each segment's 25th energy percentile), like tools/sc_corpus.py.

Same structure as tools/train_shape_vq.py (k-means per stage on the residual, then joint
re-estimation of each stage given the others), but the joint passes use the weighted
M-best search and weighted centroids in the rate-K domain, constrained to zero mean so the
codewords still live on DCT coefficients 1..K-1. CPU only: about 10 minutes for 400 k
frames on 4 cores.
"""
import argparse, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))
import vocoder_lab as vl                                       # noqa: E402

DCT = vl.DCT


def load(paths, every=2):
    xs = []
    for p in paths:
        z = np.load(p)
        sh, en, seg = z["shapes"].astype(float), z["energy"].astype(float), z["seg"]
        for s in np.unique(seg):
            i = np.where(seg == s)[0][::every]                  # the 20 ms frames the encoder codes
            e = en[i]
            keep = e > np.percentile(e, 25)
            xs.append(sh[i][keep])
    return np.concatenate(xs)


def to_k(cb):
    return np.hstack([np.zeros((len(cb), 1)), cb]) @ DCT


def to_c(cbk):
    return (cbk @ DCT.T)[:, 1:]


def search(X, W, cbk, m=8, chunk=4000):
    """Weighted M-best search, X/W (n, K) -> path indices (n, stages)."""
    out = []
    for i0 in range(0, len(X), chunk):
        x, w = X[i0:i0 + chunk], W[i0:i0 + chunk]
        n = len(x)
        paths = np.zeros((n, 1, 0), int)
        recon = np.zeros((n, 1, vl.K))
        for cb in cbk:
            r = x[:, None] - recon                                         # n P K
            rw = r * w[:, None]
            d = (r * rw).sum(-1)[..., None] - 2 * rw @ cb.T + (w @ (cb ** 2).T)[:, None, :]
            C = d.shape[2]
            k = min(m, d.shape[1] * C)
            keep = np.argpartition(d.reshape(n, -1), k - 1, 1)[:, :k]
            pi, ci = keep // C, keep % C
            paths = np.concatenate([np.take_along_axis(paths, pi[..., None], 1), ci[..., None]], 2)
            recon = np.take_along_axis(recon, pi[..., None], 1) + cb[ci]
        best = ((((x[:, None] - recon) ** 2) * w[:, None]).sum(-1)).argmin(1)
        out.append(paths[np.arange(n), best])
    return np.concatenate(out)


def centroid0(T, W):
    """argmin_y sum_i sum_k W_ik (T_ik - y_k)^2 subject to sum_k y_k = 0."""
    a, b = W.sum(0) + 1e-9, (W * T).sum(0)
    lam = (b / a).sum() / (1 / a).sum()
    return (b - lam) / a


def train(X, W, bits, m=8, joint=6, seed=0, log=print):
    from sklearn.cluster import KMeans
    c = (X @ DCT.T)[:, 1:]
    r = c.copy()
    cbk = []
    for b in bits:                                   # unweighted k-means start, as train_shape_vq
        sub = r[np.random.default_rng(seed).permutation(len(r))[:200000]]
        km = KMeans(2 ** b, n_init=1, max_iter=20, random_state=seed).fit(sub)
        cbk.append(to_k(km.cluster_centers_))
        lab = km.predict(r)
        r = r - km.cluster_centers_[lab]
    for it in range(joint):
        idx = search(X, W, cbk, m)
        rec = sum(cbk[s][idx[:, s]] for s in range(len(bits)))
        log(f"pass {it}: weighted err {np.mean(((X - rec) ** 2 * W).sum(1)) / vl.K:.3f}, "
            f"plain {np.mean((X - rec) ** 2):.3f} dB^2", flush=True)
        for s in range(len(bits)):
            T = X - sum(cbk[t][idx[:, t]] for t in range(len(bits)) if t != s)
            order = np.argsort(idx[:, s], kind="stable")
            bounds = np.searchsorted(idx[order, s], np.arange(2 ** bits[s] + 1))
            for k in range(2 ** bits[s]):
                sel = order[bounds[k]:bounds[k + 1]]
                if len(sel):
                    cbk[s][k] = centroid0(T[sel], W[sel])
    return [to_c(cb) for cb in cbk]


def main():
    a = argparse.ArgumentParser()
    a.add_argument("corpus", nargs="+")
    a.add_argument("--out", required=True)
    a.add_argument("--bits", default="9,9,8,8")
    a.add_argument("--joint", type=int, default=6)
    a.add_argument("--gamma", type=float, default=0.5)
    a.add_argument("--floor", type=float, default=40.0)
    a.add_argument("--unweighted", action="store_true")
    a.add_argument("--max-frames", type=int, default=600000)
    a = a.parse_args()
    X = load(a.corpus)
    X = X[np.random.default_rng(1).permutation(len(X))[:a.max_frames]]
    W = np.ones_like(X) if a.unweighted else vl.shape_weights(X, a.gamma, a.floor)
    print(len(X), "training frames", flush=True)
    bits = tuple(int(b) for b in a.bits.split(","))
    cb = train(X, W, bits, joint=a.joint)
    q = vl.ShapeMSVQ.__new__(vl.ShapeMSVQ)
    q.bits, q.m, q.cb = bits, 8, cb
    q.save(a.out)
    print("saved", a.out)


if __name__ == "__main__":
    main()
