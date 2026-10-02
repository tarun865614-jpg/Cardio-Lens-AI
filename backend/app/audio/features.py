"""Hand-crafted acoustic features for the transparent research baseline.

Deliberately simple and inspectable: the baseline exists to give the
evaluation lab a reference point, not to be a clinical model.
"""

from __future__ import annotations

import numpy as np
from scipy import signal, stats

from .preprocess import ANALYSIS_SR, bandpass, db, envelope_periodicity, frame_rms, shannon_envelope

FEATURES_VERSION = "feat-1.0"
_EDGES = np.geomspace(25, 900, 11)

FEATURE_NAMES = (
    [f"logband_{int(a)}_{int(b)}" for a, b in zip(_EDGES[:-1], _EDGES[1:])]
    + ["spectral_centroid", "spectral_flatness", "snr_db", "periodicity", "cycle_rate", "env_kurtosis", "env_skew", "zcr"]
)


def extract(x: np.ndarray, sr: int = ANALYSIS_SR) -> np.ndarray:
    assert sr == ANALYSIS_SR, "features expect the analysis sample rate"
    x = bandpass(x, sr, 25, 900)
    x = x / (np.std(x) or 1.0)
    f, p = signal.welch(x, fs=sr, nperseg=1024)
    tot = p[(f >= 25) & (f <= 900)].sum() or 1.0
    logbands = [np.log10(p[(f >= a) & (f < b)].sum() / tot + 1e-8) for a, b in zip(_EDGES[:-1], _EDGES[1:])]
    m = (f >= 25) & (f <= 900)
    centroid = float((f[m] * p[m]).sum() / (p[m].sum() or 1.0))
    flatness = float(stats.gmean(p[m] + 1e-14) / (np.mean(p[m]) + 1e-14))
    fr = frame_rms(x, sr, 0.02)
    snr = float(db(np.percentile(fr, 95)) - db(np.percentile(fr, 10) + 1e-12))
    env = shannon_envelope(x, sr, 50)
    per, cpm = envelope_periodicity(env, 50)
    zcr = float(np.mean(np.abs(np.diff(np.sign(x))) > 0))
    return np.array(
        logbands + [centroid / 1000.0, flatness, snr / 10.0, per, (cpm or 0.0) / 100.0,
                    float(stats.kurtosis(env)) / 10.0, float(stats.skew(env)), zcr],
        dtype=np.float64,
    )
