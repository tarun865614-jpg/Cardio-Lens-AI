"""Synthetic heart-sound-like signals for demos and tests.

These are crude acoustic stand-ins (damped tone bursts at S1/S2-like timing).
They are NOT physiological simulations, carry no clinical meaning, and must
never be used to train or evaluate a diagnostic model.
"""

from __future__ import annotations

import io

import numpy as np
from scipy.io import wavfile


def _burst(sr: int, dur: float, f0: float, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(int(sr * dur)) / sr
    env = np.sin(np.pi * t / dur) ** 2
    return env * np.sin(2 * np.pi * (f0 + rng.normal(0, 3)) * t + rng.uniform(0, np.pi))


def synth_pcg(
    duration_s: float = 20.0,
    sr: int = 4000,
    bpm: float = 72.0,
    noise_rms: float = 0.01,
    irregular: float = 0.0,
    amplitude: float = 0.5,
    seed: int = 0,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.zeros(int(duration_s * sr))
    t = 0.2
    while t < duration_s - 1.0:
        rr = 60.0 / bpm * (1 + irregular * rng.uniform(-1, 1))
        i = int(t * sr)
        s1 = _burst(sr, 0.10, 55, rng)
        x[i : i + len(s1)] += s1[: len(x) - i]
        j = int((t + 0.30 * rr ** 0.5) * sr)
        s2 = _burst(sr, 0.08, 80, rng) * 0.7
        if j < len(x):
            x[j : j + len(s2)] += s2[: len(x) - j]
        t += rr
    x = x / (np.max(np.abs(x)) or 1) * amplitude
    x += rng.normal(0, noise_rms, len(x))
    return x


def to_wav_bytes(x: np.ndarray, sr: int, dtype: str = "int16") -> bytes:
    buf = io.BytesIO()
    if dtype == "int16":
        data = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)
    else:
        data = x.astype(np.float32)
    wavfile.write(buf, sr, data)
    return buf.getvalue()
