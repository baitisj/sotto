"""Train sotto v3's shape quantizer (3-stage VQ, 12 + 11 + 11 bits).

Usage: python tools/train_shape_vq.py TRAIN.npz [TRAIN2.npz ...] [--out OUT.npz]
Each TRAIN.npz comes from tools/sc_corpus.py or tools/clean_corpus.py. Codec 2's own test recordings (with the ve9qrp
test window removed) are added to it. 5,000 random frames are held out to report the
distortion of the VQ against the scalar quantizer trained on the same data.
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sim"))
import vocoder_lab as vl                                       # noqa: E402

args = sys.argv[1:]
out = os.path.join(os.path.dirname(HERE), "sim", "data", "shape_msvq_34.npz")
if "--out" in args:
    i = args.index("--out")
    out = args[i + 1]
    del args[i:i + 2]
tr = np.concatenate([np.load(a)["shapes"] for a in args] + [vl.training_set("tracked2").astype(np.float32)])
print(len(tr), "training frames", flush=True)
idx = np.random.default_rng(0).permutation(len(tr))
te, tr = tr[idx[:5000]], tr[idx[5000:]]
sq = vl.ShapeQ(tr[::4])
vq = vl.ShapeMSVQ(tr, bits=(12, 11, 11), iters=20, joint=2)
for name, q in (("scalar, 34 bits", sq), ("3-stage VQ, 34 bits", vq)):
    print(f"{name}: held-out mean squared error {np.mean((q.quantize(te) - te) ** 2):.2f} dB^2")
vq.save(out)
print("saved", out)
