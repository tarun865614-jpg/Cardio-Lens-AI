"""Evaluation metrics with confidence intervals.

* Proportions (sensitivity, specificity, PPV, NPV, accuracy, failed-recording
  rate) use Wilson score intervals.
* AUC uses a patient-level (cluster) bootstrap, since recordings from the same
  patient are not independent.
* Any metric whose denominator is zero is reported as `None` with a reason —
  never imputed.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> dict:
    if n == 0:
        return {"value": None, "ci_low": None, "ci_high": None, "k": k, "n": n, "reason": "no cases in denominator"}
    p = k / n
    den = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n * n)) / den
    return {"value": round(p, 4), "ci_low": round(max(0.0, centre - half), 4), "ci_high": round(min(1.0, centre + half), 4), "k": k, "n": n}


def confusion(y: np.ndarray, yhat: np.ndarray) -> dict:
    return {
        "tp": int(np.sum((y == 1) & (yhat == 1))),
        "fp": int(np.sum((y == 0) & (yhat == 1))),
        "tn": int(np.sum((y == 0) & (yhat == 0))),
        "fn": int(np.sum((y == 1) & (yhat == 0))),
    }


def roc_curve(y: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    order = np.argsort(-s, kind="mergesort")
    s, y = s[order], y[order]
    distinct = np.where(np.diff(s))[0]
    idx = np.r_[distinct, y.size - 1]
    tps = np.cumsum(y)[idx]
    fps = 1 + idx - tps
    P, N = y.sum(), y.size - y.sum()
    tpr = np.r_[0, tps / P] if P else np.r_[0, tps * 0.0]
    fpr = np.r_[0, fps / N] if N else np.r_[0, fps * 0.0]
    thr = np.r_[np.inf, s[idx]]
    return fpr, tpr, thr


def auc(y: np.ndarray, s: np.ndarray) -> float | None:
    if y.sum() == 0 or y.sum() == y.size:
        return None
    fpr, tpr, _ = roc_curve(y, s)
    return float(np.trapezoid(tpr, fpr))


def cluster_bootstrap_auc(y, s, groups, n_boot: int = 1000, seed: int = 0) -> tuple[float | None, float | None]:
    rng = np.random.default_rng(seed)
    by = defaultdict(list)
    for i, g in enumerate(groups):
        by[g].append(i)
    keys = list(by)
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        idx = np.concatenate([by[keys[j]] for j in pick])
        a = auc(y[idx], s[idx])
        if a is not None:
            vals.append(a)
    if len(vals) < n_boot * 0.5:
        return None, None
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def calibration(y: np.ndarray, s: np.ndarray, bins: int = 10) -> dict:
    edges = np.linspace(0, 1, bins + 1)
    out, ece = [], 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (s >= a) & ((s < b) if b < 1 else (s <= b))
        if m.sum() == 0:
            continue
        mp, fo = float(s[m].mean()), float(y[m].mean())
        ece += m.sum() / len(s) * abs(mp - fo)
        out.append({"bin_low": round(a, 2), "bin_high": round(b, 2), "n": int(m.sum()), "mean_predicted": round(mp, 4), "observed_rate": round(fo, 4)})
    brier = float(np.mean((s - y) ** 2))
    # Calibration slope/intercept via logistic regression of y on logit(s).
    slope = intercept = None
    if 0 < y.sum() < len(y):
        z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / (1 - np.clip(s, 1e-6, 1 - 1e-6)))
        X = np.c_[np.ones_like(z), z]
        w = np.zeros(2)
        for _ in range(50):  # Newton-Raphson
            p = 1 / (1 + np.exp(-X @ w))
            H = X.T @ (X * (p * (1 - p))[:, None]) + 1e-6 * np.eye(2)
            w -= np.linalg.solve(H, X.T @ (p - y))
        intercept, slope = round(float(w[0]), 3), round(float(w[1]), 3)
    return {"bins": out, "ece": round(float(ece), 4), "brier": round(brier, 4), "slope": slope, "intercept": intercept}


def binary_metrics(y, s, groups, threshold: float, n_boot: int = 1000) -> dict:
    y = np.asarray(y, dtype=int)
    s = np.asarray(s, dtype=float)
    yhat = (s >= threshold).astype(int)
    cm = confusion(y, yhat)
    a = auc(y, s)
    lo, hi = cluster_bootstrap_auc(y, s, groups, n_boot=n_boot) if a is not None else (None, None)
    fpr, tpr, thr = roc_curve(y, s) if a is not None else (np.array([]), np.array([]), np.array([]))
    # Downsample ROC for display.
    if len(fpr) > 200:
        keep = np.unique(np.linspace(0, len(fpr) - 1, 200).astype(int))
        fpr, tpr, thr = fpr[keep], tpr[keep], thr[keep]
    return {
        "n": int(len(y)),
        "n_positive": int(y.sum()),
        "n_negative": int(len(y) - y.sum()),
        "prevalence": round(float(y.mean()), 4) if len(y) else None,
        "threshold": threshold,
        "confusion": cm,
        "sensitivity": wilson(cm["tp"], cm["tp"] + cm["fn"]),
        "specificity": wilson(cm["tn"], cm["tn"] + cm["fp"]),
        "ppv": wilson(cm["tp"], cm["tp"] + cm["fp"]),
        "npv": wilson(cm["tn"], cm["tn"] + cm["fn"]),
        "accuracy": wilson(cm["tp"] + cm["tn"], len(y)),
        "auc": {"value": None if a is None else round(a, 4), "ci_low": None if lo is None else round(lo, 4),
                "ci_high": None if hi is None else round(hi, 4), "method": "patient-level cluster bootstrap",
                **({"reason": "requires both positive and negative cases"} if a is None else {})},
        "roc": [{"fpr": round(float(f), 4), "tpr": round(float(t), 4), "threshold": None if not np.isfinite(h) else round(float(h), 4)}
                for f, t, h in zip(fpr, tpr, thr)],
        "calibration": calibration(y, s) if len(y) else None,
    }
