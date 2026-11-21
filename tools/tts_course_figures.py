#!/usr/bin/env python3
"""Figures and listening clips for the sotto-tts course (docs/tts-course/).

    python tools/tts_course_figures.py --models KOKORO_DIR [--old-table OLD_DIPHONE.stt]
        [--hunt HUNT.json]

KOKORO_DIR holds kokoro-v1.0.onnx, the duration model and voices-v1.0.bin (see
docs/sotto-tts.md); Kokoro af_sarah reads the reference clips. --old-table is a diphone
table from before the rough-patch checks (git show 228be5c:tts/data/diphone.stt), for
chapter 6's before-and-after; --hunt is a tools/diphone_hunt.py hunt.json for chapter 7.
Without them those figures are skipped.

Writes docs/tts-course/figures/*.svg and docs/tts-course/audio/*.flac.
SPDX-License-Identifier: MIT
"""
import argparse, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim"), os.path.join(ROOT, "tools")]
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from scipy import signal  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402
from audio_io import write_flac  # noqa: E402
from tts import synth, frontend  # noqa: E402

OUT = os.path.join(ROOT, "docs", "tts-course")
FS = 8000
SENT = "The birch canoe slid on the smooth planks."
CALL = "This is AG7EW on 440.850 megahertz."
QUESTION = "Is the repeater on tonight?"

# the sotto course's palette (tools/course_figures.py)
BG, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, YELLOW, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"
SPEC = LinearSegmentedColormap.from_list("spec", [BG, "#9cc3ef", BLUE, "#0d2c52"])
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10.5,
    "font.family": "DejaVu Sans", "lines.linewidth": 2, "legend.frameon": False,
    "svg.fonttype": "none", "svg.hashsalt": "sotto-tts-course",
})


def save(fig, name):
    fig.savefig(os.path.join(OUT, "figures", name), format="svg", bbox_inches="tight",
                metadata={"Date": None})
    plt.close(fig)
    print("wrote", name)


def clip(name, x):
    write_flac(os.path.join(OUT, "audio", name), np.asarray(x) * 0.9 / max(1e-9, np.abs(x).max()), FS)
    print("wrote", name, f"{len(x) / FS:.1f} s")


def spectrogram(ax, x, vmax_db=None):
    f, t, S = signal.spectrogram(x, FS, window="hann", nperseg=256, noverlap=224, nfft=512)
    S = 10 * np.log10(S + 1e-12)
    top = vmax_db if vmax_db is not None else S.max()
    ax.pcolormesh(t, f, S, cmap=SPEC, vmin=top - 65, vmax=top, shading="auto", rasterized=True)
    ax.set_ylim(0, 4000)
    ax.set_yticks([0, 1000, 2000, 3000, 4000], ["0", "1k", "2k", "3k", "4k"])
    ax.grid(False)
    return top


def tts(text, tab, **kw):
    """Speech, the parameter track and the phone plan for text."""
    p, rep = synth.synth_params(text, tab, **kw)
    bits = synth.encode(p)
    return synth.decode_c(bits) / 32768.0, p, len(bits)


class Ref:
    """Kokoro af_sarah, given the front end's own phones, at 8 kHz."""

    def __init__(self, models):
        import tts_corpus
        self.tc = tts_corpus
        self.k = tts_corpus.Kokoro(models, "af_sarah")

    def say(self, text):
        utt = []
        for ph in frontend.text_to_phrases(text):
            for i, w in enumerate(ph["words"]):
                utt.append((w["phones"], ph["end"] if i == len(ph["words"]) - 1 else ""))
        y, segs = self.k.say(utt)
        x = self.tc.level(resample_poly(y, 1, 3))
        return x, [(p, t0 + 0.05, t1 + 0.05) for p, s, wi, t0, t1 in segs]   # audio leads 50 ms


# ---------------------------------------------------------------- 1. the pipeline
def fig_pipeline():
    steps = [
        ("Text", "This is AG7EW."),
        ("Front end", "this is alfa golf\nseven echo whiskey"),
        ("Phones", "DH IH S  IH Z\nAE L F AX ..."),
        ("Timing and pitch", "how long each phone,\nthe melody"),
        ("Sound pieces", "diphones from\nthe table"),
        ("20 ms frames", "voicing, pitch,\nenergy, shape"),
        ("sotto 1200 coder", "6 bytes every\n40 ms"),
        ("Decoder", "the radio's own,\nalready there"),
    ]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.set_xlim(0, 4 * 2.5)
    ax.set_ylim(0, 4.4)
    ax.axis("off")
    W, H = 1.9, 0.62
    pos = [(0.15 + 2.5 * i, 3.0) for i in range(4)] + [(0.15 + 2.5 * (3 - i), 0.85) for i in range(4)]
    for i, ((name, ex), (x, y)) in enumerate(zip(steps, pos)):
        col = ORANGE if i >= 6 else BLUE
        ax.add_patch(FancyBboxPatch((x, y), W, H, boxstyle="round,pad=0.02,rounding_size=0.08",
                                    fc=BG, ec=col, lw=2))
        ax.text(x + W / 2, y + H / 2, name, ha="center", va="center", fontsize=10.5, weight="bold", color=INK)
        ax.text(x + W / 2, y - 0.12, ex, ha="center", va="top", fontsize=8.5, color=INK2,
                family="DejaVu Sans Mono")
        if i < len(steps) - 1:
            nx, ny = pos[i + 1]
            if ny == y:
                x0, x1 = (x + W + 0.04, nx - 0.04) if nx > x else (x - 0.04, nx + W + 0.04)
                ax.annotate("", (x1, y + H / 2), (x0, y + H / 2),
                            arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.4))
            else:
                ax.annotate("", (x + W + 0.25, ny + H / 2), (x + W + 0.04, y + H / 2),
                            arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.4,
                                            connectionstyle="arc,angleA=0,angleB=0,armA=18,armB=18,rad=6"))
    ax.text(0.15, 4.3, "sotto-tts (blue) only writes the frames; the sotto parts (orange) already exist on the radio",
            fontsize=10, color=INK2, va="top")
    save(fig, "pipeline.svg")


# ---------------------------------------------------------------- 2. phones and the plan
def fig_plan(ref, tab):
    seq, phrases = synth.phone_plan(QUESTION, tab)
    n = int(np.ceil(seq[-1]["t1"] / synth.FRAME))
    f0 = synth.f0_track(seq, phrases, tab["f0"], n)
    x, segs = ref.say(QUESTION)
    import librosa
    fp, vp, _ = librosa.pyin(x.astype(np.float32), fmin=70, fmax=450, sr=FS, frame_length=512, hop_length=160)
    tp = np.arange(len(fp)) * 0.02
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 4.6), sharex=False, gridspec_kw=dict(height_ratios=[1, 2]))
    a1.set_title(f"The plan for “{QUESTION}”: each phone gets a time slot")
    for q in seq:
        if q["p"] == "PAU":
            continue
        vowel = q["p"] in synth.VOWELS if hasattr(synth, "VOWELS") else synth.is_vowel(q["p"])
        a1.add_patch(plt.Rectangle((q["t0"], 0), q["t1"] - q["t0"], 1, fc=(BLUE if vowel else GRID),
                                   ec=BG, lw=1.5, alpha=0.85 if vowel else 1))
        a1.text(0.5 * (q["t0"] + q["t1"]), 0.5, q["p"], ha="center", va="center", fontsize=8.5,
                color=BG if vowel else INK)
    a1.set_xlim(0, seq[-1]["t1"])
    a1.set_ylim(0, 1)
    a1.set_yticks([])
    a1.grid(False)
    a1.set_xlabel("seconds (vowels in blue)")
    a2.set_title("Its melody: the pitch rules (orange) and Kokoro reading the same phones (gray)")
    t = np.arange(n) * synth.FRAME
    a2.plot(tp[vp], fp[vp], ".", ms=4, color=INK2, label="Kokoro af_sarah (measured)")
    a2.plot(t, f0, color=ORANGE, label="sotto-tts rules")
    a2.set_ylabel("pitch (Hz)")
    a2.set_xlabel("seconds")
    a2.set_ylim(100, 400)
    a2.legend(loc="upper left")
    fig.tight_layout()
    save(fig, "plan.svg")


# ---------------------------------------------------------------- 3. diphones
def fig_diphones(ref):
    from tts import phones as P  # noqa: F401
    x, segs = ref.say("Golf.")
    s = [(p, t0, t1) for p, t0, t1 in segs if p != "PAU"]
    # Kokoro hands the pause after a word to its last phone; end it where its energy fades
    # (tools/tts_build.py trims the same way)
    p, t0, t1 = s[-1]
    e = np.array([np.sqrt(np.mean(x[int(t * FS):int(t * FS) + 80] ** 2)) for t in np.arange(t0, t1, 0.01)])
    keep = np.flatnonzero(20 * np.log10(e + 1e-9) > 20 * np.log10(e.max()) - 20)
    s[-1] = (p, t0, t0 + 0.01 * (keep[-1] + 1))
    t_lo, t_hi = s[0][1] - 0.12, s[-1][2] + 0.12
    i0, i1 = int(t_lo * FS), int(t_hi * FS)
    y = x[i0:i1]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 4.8), sharex=True, gridspec_kw=dict(height_ratios=[1, 2.2]))
    tt = np.arange(len(y)) / FS
    a1.plot(tt, y, color=INK2, lw=0.6)
    a1.set_yticks([])
    a1.set_title("“Golf” said by Kokoro: phones (top) and the diphones cut from them (bottom)")
    spectrogram(a2, y)
    edges = [s[0][1] - t_lo] + [q[2] - t_lo for q in s]
    for e in edges:
        for a in (a1, a2):
            a.axvline(e, color=INK, lw=0.8, ls=(0, (3, 3)))
    for p, t0, t1 in s:
        a1.text(0.5 * (t0 + t1) - t_lo, a1.get_ylim()[1] * 0.8, p, ha="center", fontsize=11, weight="bold")
    mids = [0.0] + [0.5 * (q[1] + q[2]) - t_lo for q in s] + [len(y) / FS]
    names = ["PAU"] + [q[0] for q in s] + ["PAU"]
    cols = [ORANGE, AQUA, VIOLET, YELLOW, ORANGE]
    for k in range(len(mids) - 1):
        lo, hi = max(mids[k], 0.03), min(mids[k + 1], len(y) / FS - 0.03)
        yv = 3600 - 260 * (k % 2)
        a2.annotate("", (lo, yv), (hi, yv), arrowprops=dict(arrowstyle="<->", color=cols[k % 5], lw=2))
        a2.text(0.5 * (lo + hi), yv + 90, f"{names[k]}-{names[k + 1]}", ha="center", fontsize=9.5,
                color=INK, weight="bold", bbox=dict(fc=BG, ec="none", pad=1))
    a2.set_ylabel("frequency (Hz)")
    a2.set_xlabel("seconds: each diphone runs from the middle of one phone to the middle of the next")
    fig.tight_layout()
    save(fig, "diphones.svg")


# ---------------------------------------------------------------- 4. three voices compared
def fig_compare(ref, dtab, rtab):
    import sotto_lr
    x, _ = ref.say(SENT)
    xs = synth.decode_c(sotto_lr.Sotto1200().encode(x)) / 32768.0
    yd, _, _ = tts(SENT, dtab)
    yr, _, _ = tts(SENT, rtab)
    clip("kokoro.flac", x)
    clip("kokoro_sotto.flac", xs)
    clip("diphone.flac", yd)
    clip("robot.flac", yr)
    rows = [("Kokoro af_sarah, then through sotto 1200 (the best the table could hope for)", xs),
            ("sotto-tts, diphone table (37 KB)", yd),
            ("sotto-tts, robot table (493 bytes)", yr)]
    fig, axs = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
    top = None
    for a, (title, y) in zip(axs, rows):
        e = np.sqrt(np.convolve(y ** 2, np.ones(400) / 400, "same"))
        on = np.flatnonzero(e > e.max() * 0.03)
        y = y[max(0, on[0] - 400):on[-1] + 400]
        top = spectrogram(a, y, top)
        a.set_title(title, fontsize=11)
        a.set_ylabel("Hz")
    axs[0].set_xlim(0, 2.9)
    axs[-1].set_xlabel(f"seconds: “{SENT}”")
    fig.tight_layout()
    save(fig, "compare.svg")


# ---------------------------------------------------------------- 5. melody matters
def clips_prosody(dtab):
    y, _, _ = tts(SENT, dtab)
    old = synth.f0_track
    synth.f0_track = lambda seq, phrases, f0, n: np.full(n, f0)
    try:
        yf, _, _ = tts(SENT, dtab)
    finally:
        synth.f0_track = old
    clip("flat.flac", yf)
    yq, _, _ = tts(QUESTION, dtab)
    clip("question.flac", yq)


# ---------------------------------------------------------------- 6. the frames
def fig_frames(dtab):
    y, p, nsf = tts(CALL, dtab)
    yn, _, _ = tts(CALL, dtab, words=None)
    clip("callsign_words.flac", y)
    clip("callsign_diphones.flac", yn)
    import sotto_lr
    lr = sotto_lr.Sotto1200()
    n = len(p["code"])
    t = np.arange(n) * synth.FRAME
    f0 = np.array([lr.wo_value(int(w)) * FS / (2 * np.pi) for w in p["wi"]])
    seq, phrases = synth.phone_plan(CALL, dtab)
    fig, axs = plt.subplots(4, 1, figsize=(10, 7.2), sharex=True, gridspec_kw=dict(height_ratios=[1.1, 0.6, 1, 1.6]))
    a0, a1, a2, a3 = axs
    tw = np.arange(len(y)) / FS
    a0.plot(tw, y, color=INK2, lw=0.5)
    a0.set_yticks([])
    a0.set_title(f"“{CALL}”: what sotto-tts hands the coder, one column per 20 ms frame")
    k = 0
    for j, ph in enumerate(phrases):
        P = [q for q in seq if q["phrase"] == j and q["p"] != "PAU"]
        for wi, w in enumerate(ph["words"]):
            Q = [q for q in P if q["word"] == wi]
            if Q:
                a0.text(0.5 * (Q[0]["t0"] + Q[-1]["t1"]), a0.get_ylim()[1] * 0.95, w["text"], ha="center",
                        va="top", fontsize=8, rotation=0, color=INK)
    v = np.where(p["code"] > 0, 1, 0)
    a1.bar(t, v, width=synth.FRAME, align="edge", color=AQUA, lw=0)
    a1.set_yticks([0, 1], ["hiss", "voiced"])
    a1.set_ylim(0, 1.2)
    a1.grid(False)
    a1.set_title("voicing", fontsize=10.5)
    a2.plot(t[p["code"] > 0], f0[p["code"] > 0], ".", ms=3.5, color=ORANGE)
    a2.set_ylabel("pitch (Hz)")
    a2.set_ylim(80, 400)
    a2.set_title("pitch (only matters when voiced)", fontsize=10.5)
    import vocoder_lab as vl
    env = p["shape"]                                     # dB envelope at the 20 mel points
    E = env + (p["ei"][:, None] * 2.0)
    E[p["ei"] == 0] = E.min()
    a3.pcolormesh(np.r_[t, t[-1] + synth.FRAME], np.arange(env.shape[1] + 1), E.T, cmap=SPEC,
                  shading="flat", rasterized=True)
    a3.set_yticks([0.5, env.shape[1] - 0.5], ["low", "high"])
    a3.set_ylabel("envelope")
    a3.grid(False)
    a3.set_title("energy and spectral shape (darker = louder)", fontsize=10.5)
    a3.set_xlabel(f"seconds: {n} frames, packed into {nsf} superframes = {6 * nsf} bytes")
    fig.tight_layout()
    save(fig, "frames.svg")


# ---------------------------------------------------------------- 7. a rough patch, fixed
def fig_rough(old_tab, new_tab):
    rows = []
    for name, tab in (("before", old_tab), ("after", new_tab)):
        y, p, _ = tts("Happy.", tab, words=None)
        clip(f"happy_{name}.flac", y)
        rows.append((name, y, p))
    fig, axs = plt.subplots(2, 2, figsize=(10, 4.6), sharex="col", gridspec_kw=dict(height_ratios=[2, 0.6]))
    top = None
    for c, (name, y, p) in enumerate(rows):
        top = spectrogram(axs[0, c], y, top)
        axs[0, c].set_title(f"“happy” {name} the build checks", fontsize=11)
        t = np.arange(len(p["code"])) * synth.FRAME
        axs[1, c].bar(t, np.where(p["code"] > 0, 1, 0), width=synth.FRAME, align="edge", color=AQUA, lw=0)
        axs[1, c].bar(t, np.where((p["code"] == 0) & (p["ei"] > 0), 1, 0), width=synth.FRAME, align="edge",
                      color=ORANGE, lw=0)
        axs[1, c].set_yticks([])
        axs[1, c].grid(False)
        axs[1, c].set_xlabel("seconds (green voiced, orange hiss)")
    axs[0, 0].set_ylabel("Hz")
    fig.tight_layout()
    save(fig, "rough-patch.svg")


# ---------------------------------------------------------------- 8. the hunt
def fig_hunt(hunt_json):
    import json
    d = json.load(open(hunt_json))
    it = d["items"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 3.8))
    for k, col, lab in (("table_damage", BLUE, "sotto-tts table vs Kokoro"),
                        ("codec_damage", ORANGE, "sotto 1200 coder vs Kokoro")):
        v = np.array([x[k] for x in it])
        a1.hist(v, bins=np.arange(0, 36, 1), color=col, alpha=0.7, label=lab)
    a1.set_title(f"Damage scores for all {len(it):,} diphones")
    a1.set_xlabel("damage (higher = further from Kokoro)")
    a1.set_ylabel("diphones")
    a1.legend()
    worst = sorted(it, key=lambda x: -x["table_damage"])[:10]
    a2.barh(range(len(worst))[::-1], [x["table_damage"] for x in worst], color=BLUE)
    a2.set_yticks(range(len(worst))[::-1], [f"{x['pair']}  “{x['text']}”" for x in worst], fontsize=9)
    a2.set_title("The ten worst: where to listen first")
    a2.set_xlabel("table damage")
    a2.grid(axis="y", visible=False)
    fig.tight_layout()
    save(fig, "hunt.svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True)
    ap.add_argument("--old-table")
    ap.add_argument("--hunt", help="a hunt.json from tools/diphone_hunt.py, for the hunt figure")
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "figures"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "audio"), exist_ok=True)
    dtab = synth.load_table(os.path.join(ROOT, "tts", "data", "diphone.stt"))
    rtab = synth.load_table(os.path.join(ROOT, "tts", "data", "robot.stt"))
    ref = Ref(a.models)
    fig_pipeline()
    fig_plan(ref, dtab)
    fig_diphones(ref)
    fig_compare(ref, dtab, rtab)
    clips_prosody(dtab)
    fig_frames(dtab)
    if a.old_table:
        fig_rough(synth.load_table(a.old_table), dtab)
    if a.hunt:
        fig_hunt(a.hunt)


if __name__ == "__main__":
    main()
