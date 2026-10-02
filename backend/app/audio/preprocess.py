"""Deterministic signal-processing primitives shared by quality analysis and model adapters.

Anything a *model* needs beyond this (specific filtering, normalisation,
segmentation) is declared in that model's input specification and applied by
its adapter, so the validated preprocessing pipeline is reproduced exactly.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from scipy import signal

ANALYSIS_SR = 2000  # Hz; heart-sound energy of interest lies below ~1 kHz


def remove_dc(x: np.ndarray) -> np.ndarray:
    return x - np.mean(x) if x.size else x


def resample(x: np.ndarray, sr: int, target_sr: int = ANALYSIS_SR) -> np.ndarray:
    if sr == target_sr:
        return x.copy()
    frac = Fraction(target_sr, sr).limit_denominator(1000)
    return signal.resample_poly(x, frac.numerator, frac.denominator)


def bandpass(x: np.ndarray, sr: int, lo: float, hi: float, order: int = 4) -> np.ndarray:
    hi = min(hi, sr / 2 * 0.95)
    sos = signal.butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, x)


def highpass(x: np.ndarray, sr: int, fc: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, fc, btype="highpass", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, x)


def frame_rms(x: np.ndarray, sr: int, frame_s: float) -> np.ndarray:
    n = max(1, int(sr * frame_s))
    k = len(x) // n
    if k == 0:
        return np.array([np.sqrt(np.mean(x**2))]) if x.size else np.array([0.0])
    return np.sqrt(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1))


def db(x: float | np.ndarray, floor: float = 1e-12):
    return 20.0 * np.log10(np.maximum(x, floor))


def shannon_envelope(x: np.ndarray, sr: int, out_sr: int = 50) -> np.ndarray:
    """Normalised average Shannon energy envelope, a standard PCG envelope."""
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak <= 0:
        return np.zeros(max(1, len(x) * out_sr // sr))
    xn = x / peak
    e = -(xn**2) * np.log(xn**2 + 1e-10)
    win = max(1, int(0.02 * sr))
    e = np.convolve(e, np.ones(win) / win, mode="same")
    env = resample(e, sr, out_sr)
    sd = np.std(env)
    return (env - np.mean(env)) / sd if sd > 0 else env * 0.0


def envelope_periodicity(env: np.ndarray, env_sr: int, min_bpm: float = 30, max_bpm: float = 200) -> tuple[float, float | None]:
    """Peak normalised autocorrelation of the envelope within a plausible cardiac-cycle lag range.

    Returns (periodicity_index in [0,1], cycles_per_minute at that lag or None).
    A low value means "no consistent cycle was found" — which can be caused by
    noise *or* by a genuinely irregular rhythm, so it is never a pass/fail gate.
    """
    n = len(env)
    lo = int(env_sr * 60.0 / max_bpm)
    hi = int(env_sr * 60.0 / min_bpm)
    if n < 2 * hi or np.allclose(env, 0):
        return 0.0, None
    ac = signal.correlate(env, env, mode="full", method="fft")[n - 1 :]
    ac = ac / (ac[0] if ac[0] > 0 else 1.0)
    # Unbiased correction so longer lags aren't penalised.
    ac = ac * n / (n - np.arange(n))
    seg = ac[lo : hi + 1]
    i = int(np.argmax(seg))
    return float(np.clip(seg[i], 0.0, 1.0)), 60.0 * env_sr / (lo + i)


def minmax_waveform(x: np.ndarray, buckets: int = 800) -> list[list[float]]:
    if x.size == 0:
        return []
    buckets = min(buckets, x.size)
    edges = np.linspace(0, x.size, buckets + 1).astype(int)
    return [[round(float(x[a:b].min()), 4), round(float(x[a:b].max()), 4)] for a, b in zip(edges[:-1], edges[1:]) if b > a]


def coarse_spectrogram(x: np.ndarray, sr: int, max_hz: float = 1000, max_frames: int = 240, n_bins: int = 48) -> dict:
    nper = int(0.064 * sr)
    f, t, S = signal.spectrogram(x, fs=sr, nperseg=nper, noverlap=nper // 2, scaling="spectrum")
    keep = f <= max_hz
    f, S = f[keep], S[keep]
    # Pool to a small fixed grid for display.
    if S.shape[1] > max_frames:
        idx = np.linspace(0, S.shape[1], max_frames + 1).astype(int)
        S = np.stack([S[:, a:b].mean(axis=1) for a, b in zip(idx[:-1], idx[1:])], axis=1)
        t = np.array([t[a:b].mean() for a, b in zip(idx[:-1], idx[1:])])
    fidx = np.linspace(0, S.shape[0], n_bins + 1).astype(int)
    S = np.stack([S[a:b].mean(axis=0) for a, b in zip(fidx[:-1], fidx[1:])], axis=0)
    f = np.array([f[a:b].mean() for a, b in zip(fidx[:-1], fidx[1:])])
    Sdb = 10 * np.log10(S + 1e-14)
    top = np.percentile(Sdb, 99.5)
    Sdb = np.clip(Sdb, top - 60, top)
    norm = ((Sdb - (top - 60)) / 60 * 255).astype(int)
    return {"freqs_hz": [round(float(v), 1) for v in f], "times_s": [round(float(v), 3) for v in t], "db_u8": norm.tolist(), "range_db": 60}
