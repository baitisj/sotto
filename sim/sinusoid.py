"""Python sinusoidal analysis matching Codec 2's (sine.c), so pitch and voicing can be
swapped without going through c2sim's own estimators.

Frame i is the 320-sample buffer ending at sample (i + 1) * 80, windowed by Codec 2's
279-point Hann window centred in it and transformed with a 512-point FFT, exactly as
c2sim does. Output is the same MODEL record vocoder_lab uses, so c2sim --modelin can
synthesise it.
"""
import numpy as np

import vocoder_lab as vl

N, M_PITCH, NW, NFFT = 80, 320, 279, 512
FS = vl.FS
WO_MIN, WO_MAX = vl.WO_MIN, vl.WO_MAX
WO_MAX_HI = 2 * np.pi / 16                       # 500 Hz, for voices above Codec 2's 400 Hz


def _window():
    w = np.zeros(M_PITCH)
    lo = M_PITCH // 2 - NW // 2
    w[lo:lo + 2 * (NW // 2)] = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(2 * (NW // 2)) / (NW - 1))
    w /= np.sqrt(np.sum(w ** 2) * NFFT)
    # frequency response of the window, centred on bin NFFT/2 (for the MBE voicing fit)
    ws = np.zeros(NFFT)
    ws[:NW // 2] = w[M_PITCH // 2:M_PITCH // 2 + NW // 2]
    ws[NFFT - NW // 2:] = w[M_PITCH // 2 - NW // 2:M_PITCH // 2]
    W = np.fft.fft(ws).real
    return w, np.concatenate([W[NFFT // 2:], W[:NFFT // 2]])


WIN, WRESP = _window()


def spectra(x):
    """Complex 512-point spectra, one per 10 ms frame, aligned with c2sim's frames."""
    n = -(-len(x) // N)
    xp = np.concatenate([np.ones(M_PITCH - N), x, np.zeros(n * N - len(x))])   # c2sim starts Sn at 1.0
    out = np.zeros((n, NFFT), complex)
    for i in range(n):
        s = xp[i * N:i * N + M_PITCH] * WIN
        buf = np.zeros(NFFT)
        buf[:NW // 2] = s[M_PITCH // 2:M_PITCH // 2 + NW // 2]
        buf[NFFT - NW // 2:] = s[M_PITCH // 2 - NW // 2:M_PITCH // 2]
        out[i] = np.fft.fft(buf)
    return out


def refine(Sw, wo, wo_max=WO_MAX):
    """Codec 2's two-stage harmonic-sum refinement around an initial Wo."""
    P = np.abs(Sw) ** 2
    for span, step in ((5, 1.0), (1, 0.25)):
        L = int(np.pi / wo)
        p0 = 2 * np.pi / wo
        best, wbest = -1, wo
        for p in np.arange(p0 - span, p0 + span + 1e-9, step):
            w = 2 * np.pi / p
            b = (np.arange(1, L + 1) * w * NFFT / (2 * np.pi) + 0.5).astype(int)
            e = P[b[b < NFFT // 2]].sum()
            if e > best:
                best, wbest = e, w
        wo = wbest
    return float(np.clip(wo, WO_MIN, wo_max))


def n_harm(wo):
    wo = np.float32(wo)                          # float32 like Codec 2, for exact-integer pi/Wo
    L = int(np.floor(np.float32(np.pi) / wo))
    return L - 1 if wo * np.float32(L) >= np.float32(0.95 * np.pi) else L


def amplitudes(Sw, wo):
    L = n_harm(wo)
    r = 2 * np.pi / NFFT
    A = np.zeros(vl.MAX_AMP + 1)
    phi = np.zeros(vl.MAX_AMP + 1)
    P = np.abs(Sw) ** 2
    for m in range(1, L + 1):
        am, bm = int((m - 0.5) * wo / r + 0.5), int((m + 0.5) * wo / r + 0.5)
        A[m] = np.sqrt(P[am:bm].sum())
        b = int(m * wo / r + 0.5)
        phi[m] = np.angle(Sw[b])
    return L, A, phi


def harmonic_snr(Sw, wo, L):
    """Per-harmonic voicing SNR (dB): how well a single windowed sinusoid at m*Wo explains
    the spectrum around it. Same fit as Codec 2's est_voicing_mbe, kept per harmonic."""
    snr = np.zeros(L + 1)
    for l in range(1, L + 1):
        al = int(np.ceil((l - 0.5) * wo * NFFT / (2 * np.pi)))
        bl = int(np.ceil((l + 0.5) * wo * NFFT / (2 * np.pi)))
        off = int(NFFT / 2 - l * wo * NFFT / (2 * np.pi) + 0.5)
        Wm = WRESP[off + al:off + bl]
        S = Sw[al:bl]
        Am = (S * Wm).sum() / max((Wm ** 2).sum(), 1e-12)
        err = np.sum(np.abs(S - Am * Wm) ** 2) + 1e-12
        snr[l] = 10 * np.log10(np.sum(np.abs(S) ** 2) / err + 1e-12)
    return snr


def codec2_voicing(Sw, wo, A, L):
    """Codec 2's binary decision: SNR of the fit over harmonics below 1 kHz, > 6 dB,
    followed by its low/high energy-ratio clean-up."""
    l1k = int(L * 1000 / (FS / 2))
    sig = 1e-4 + np.sum(A[1:l1k + 1] ** 2)
    err = 1e-4
    for l in range(1, l1k + 1):
        al = int(np.ceil((l - 0.5) * wo * NFFT / (2 * np.pi)))
        bl = int(np.ceil((l + 0.5) * wo * NFFT / (2 * np.pi)))
        off = int(NFFT / 2 - l * wo * NFFT / (2 * np.pi) + 0.5)
        Wm = WRESP[off + al:off + bl]
        S = Sw[al:bl]
        Am = (S * Wm).sum() / max((Wm ** 2).sum(), 1e-12)
        err += np.sum(np.abs(S - Am * Wm) ** 2)
    v = 10 * np.log10(sig / err) > 6.0
    l2k, l4k = int(L * 2000 / (FS / 2)), int(L * 4000 / (FS / 2))
    er = 10 * np.log10((1e-4 + np.sum(A[1:l2k + 1] ** 2)) / (1e-4 + np.sum(A[l2k:l4k + 1] ** 2)))
    if not v and er > 10:
        v = True
    if v and (er < -10 or (er < -4 and wo <= 60 * 2 * np.pi / FS)):
        v = False
    return int(v)


def analyse(x, wo_track, voicing=None, do_refine=True):
    """MODEL records for speech x at the given per-frame Wo track (radians/sample).
    voicing: per-frame 0/1, or None for Codec 2's own decision at that Wo."""
    Sw = spectra(x)
    n = min(len(Sw), len(wo_track))
    m = np.zeros(n, vl.MODEL)
    for i in range(n):
        wo = refine(Sw[i], wo_track[i]) if do_refine else float(wo_track[i])
        L, A, phi = amplitudes(Sw[i], wo)
        m[i]["Wo"], m[i]["L"], m[i]["A"], m[i]["phi"] = wo, L, A, phi
        m[i]["voiced"] = codec2_voicing(Sw[i], wo, A, L) if voicing is None else int(voicing[i])
    return m


# ---------------------------------------------------------------- pitch tracking
def fit_error(Sw, wo, fmax=2500.0):
    """Normalised MBE fit error over 0..fmax Hz: residual after fitting one windowed
    sinusoid per harmonic of wo, divided by the spectral energy in that range."""
    f0 = wo * FS / (2 * np.pi)
    L = max(1, int(fmax / f0))
    k = wo * NFFT / (2 * np.pi)
    hi = int(np.ceil((L + 0.5) * k))
    err = 1e-9
    for l in range(1, L + 1):
        al, bl = int(np.ceil((l - 0.5) * k)), int(np.ceil((l + 0.5) * k))
        off = int(NFFT / 2 - l * k + 0.5)
        Wm = WRESP[off + al:off + bl]
        S = Sw[al:bl]
        Am = (S * Wm).sum() / max((Wm ** 2).sum(), 1e-12)
        err += np.sum(np.abs(S - Am * Wm) ** 2)
    return err / (np.sum(np.abs(Sw[1:hi]) ** 2) + 1e-9)


def track_pitch(Sw, wo0, voiced, mults=(1.0, 2.0, 0.5), lam=3.0, bias=0.5, fmin=70.0,
                wo_max=WO_MAX):
    """Correct octave errors in an initial Wo track. For each voiced frame the candidates are
    wo0 * mults, each refined; a Viterbi search over each voiced run minimises
    log(fit error) - bias * log(Wo) (subharmonics fit about as well as the true pitch, so
    higher Wo is favoured) plus lam * |log Wo jump| between frames."""
    n = len(wo0)
    wo = np.asarray(wo0, float).copy()
    v = np.asarray(voiced) > 0
    i = 0
    while i < n:
        if not v[i]:
            i += 1
            continue
        j = i
        while j < n and v[j]:
            j += 1
        C = np.array([[refine(Sw[t], float(np.clip(wo0[t] * mu, WO_MIN, wo_max)), wo_max) for mu in mults]
                      for t in range(i, j)])
        # candidates other than the initial estimate must stay above fmin
        bad = (C * FS / (2 * np.pi) < fmin) & (np.arange(len(mults)) > 0)[None, :]
        E = np.array([[np.log(fit_error(Sw[t], w)) - bias * np.log(w) for w in C[t - i]]
                      for t in range(i, j)]) + 1e3 * bad
        D, back = E[0].copy(), []
        for t in range(1, j - i):
            tr = D[:, None] + lam * np.abs(np.log(C[t - 1][:, None] / C[t][None, :]))
            back.append(tr.argmin(0))
            D = tr.min(0) + E[t]
        k = int(D.argmin())
        path = [k]
        for b in reversed(back):
            k = int(b[k])
            path.append(k)
        wo[i:j] = C[np.arange(j - i), path[::-1]]
        i = j
    return wo


def clean_voicing(Sw, m, voiced0, min_run=3):
    """Voicing for a re-tracked model: a frame stays voiced only if Codec 2 called it voiced
    and Codec 2's test also passes at the corrected pitch; voiced runs shorter than min_run
    frames (30 ms) are dropped. Stops junk pitch in transitions being synthesised as buzz."""
    v = np.array([int(voiced0[i] > 0 and codec2_voicing(Sw[i], m[i]["Wo"], m[i]["A"], m[i]["L"]))
                  for i in range(len(m))])
    i = 0
    while i < len(v):
        if v[i]:
            j = i
            while j < len(v) and v[j]:
                j += 1
            if j - i < min_run:
                v[i:j] = 0
            i = j
        else:
            i += 1
    return v


# Mean log fit_error() of white noise against f0 (Hz): a dense harmonic comb fits noise well,
# so a low pitch must beat this baseline, not just fit well (measured on 4 s of noise).
NOISE_F0 = np.array([50, 61, 75, 91, 111, 136, 166, 203, 248, 303, 370, 452, 500])
NOISE_LOGERR = np.array([-1.84, -1.46, -1.21, -0.93, -0.72, -0.58, -0.46, -0.36, -0.31,
                         -0.26, -0.25, -0.22, -0.21])


def noise_logerr(w):
    return np.interp(np.log(w * FS / (2 * np.pi)), np.log(NOISE_F0), NOISE_LOGERR)


def track_pitch_voicing(Sw, wo0, voiced0, lam=3.0, bias=0.5, fmin=70.0, wo_max=WO_MAX_HI,
                        uv_cost=-0.5, prior=1.0, switch=1.5, jump=4.0, norm="bias"):
    """Joint pitch and voicing track over the whole utterance (Viterbi).

    States per frame: unvoiced, or voiced at one of the candidates refine(wo0[t+d] * mu)
    for d in -1..1 and mu in 1, 2, 1/2 (a neighbour's pitch lets the track bridge a frame
    where Codec 2's estimate is junk). Costs:
      voiced at w     log(fit error) - bias * log(w), plus `prior` if Codec 2 said unvoiced
      unvoiced        uv_cost, plus `prior` if Codec 2 said voiced
      voiced->voiced  lam * |log jump|, plus jump * excess over a third of an octave
      voiced<->uv     switch
    Returns (wo, voiced)."""
    n = len(wo0)
    v0 = np.asarray(voiced0) > 0
    cands, costs = [], []
    for t in range(n):
        ws = []
        for d in (0, -1, 1):
            if 0 <= t + d < n:
                for mu in (1.0, 2.0, 0.5):
                    w = refine(Sw[t], float(np.clip(wo0[t + d] * mu, WO_MIN, wo_max)), wo_max)
                    if w * FS / (2 * np.pi) >= fmin or (d == 0 and mu == 1.0):
                        if all(abs(np.log(w / u)) > 0.01 for u in ws):
                            ws.append(w)
        ws = np.array(ws)
        le = np.array([np.log(fit_error(Sw[t], w)) for w in ws])
        le = le - noise_logerr(ws) if norm == "noise" else le - bias * np.log(ws)
        c = le + prior * (not v0[t])
        cands.append(ws)
        costs.append(np.concatenate([[uv_cost + prior * v0[t]], c]))     # state 0 = unvoiced
    D, back = costs[0].copy(), []
    for t in range(1, n):
        prev = np.concatenate([[0.0], cands[t - 1]])
        cur = np.concatenate([[0.0], cands[t]])
        tr = np.zeros((len(prev), len(cur)))
        lj = np.abs(np.log(prev[1:, None] / cur[None, 1:]))
        tr[1:, 1:] = lam * lj + jump * np.maximum(lj - np.log(2) / 3, 0)
        tr[0, 1:] = switch
        tr[1:, 0] = switch
        tot = D[:, None] + tr
        back.append(tot.argmin(0))
        D = tot.min(0) + costs[t]
    k = int(D.argmin())
    path = [k]
    for b in reversed(back):
        k = int(b[k])
        path.append(k)
    path = path[::-1]
    wo = np.asarray(wo0, float).copy()
    voiced = np.zeros(n, int)
    for t, k in enumerate(path):
        if k:
            wo[t], voiced[t] = cands[t][k - 1], 1
    return wo, voiced
