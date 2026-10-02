"""Transparent research baseline: hand-crafted features + L2 logistic regression.

    python -m app.research.baseline --manifest manifest.csv --out runs/baseline-0.1.0
    python -m app.research.baseline --circor-dir /data/circor/training_data --out runs/circor-baseline
    python -m app.research.baseline --synthetic-smoke --out /tmp/smoke   # pipeline test only

Manifest columns: path, patient_id, label (0/1), plus optional device, site, age_group, sex …

Outputs (all reproducible from the seed):
  weights.json            — loadable by LocalBaselineAdapter (validation_status forced to research_only)
  training_manifest.csv   — patient IDs used in train/val (feed to the leakage check)
  test_predictions.csv    — held-out predictions in the Research Lab upload format
  split_summary.json

The split is at PATIENT level, so no patient contributes recordings to more
than one of train / val / test. Temperature scaling is fit on val only; test
is touched exactly once.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from ..audio import features
from ..audio.decode import decode_audio
from ..audio.preprocess import ANALYSIS_SR, remove_dc, resample
from ..audio.quality import assess

VERSION = "0.1.0"


def patient_split(pid: str, seed: int) -> str:
    h = int(hashlib.sha256(f"{seed}:{pid}".encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


def fit_logreg(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 100) -> tuple[np.ndarray, float]:
    Xb = np.c_[X, np.ones(len(X))]
    w = np.zeros(Xb.shape[1])
    reg = l2 * np.eye(Xb.shape[1])
    reg[-1, -1] = 0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (p - y) + reg @ w
        H = Xb.T @ (Xb * (p * (1 - p))[:, None]) + reg + 1e-8 * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w[:-1], float(w[-1])


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    best, best_nll = 1.0, np.inf
    for T in np.geomspace(0.25, 8, 120):
        p = np.clip(1 / (1 + np.exp(-logits / T)), 1e-7, 1 - 1e-7)
        nll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
        if nll < best_nll:
            best, best_nll = float(T), nll
    return best


def recording_logit(x: np.ndarray, mean, std, coef, intercept, window_s=5.0) -> float:
    n = int(window_s * ANALYSIS_SR)
    starts = range(0, max(1, len(x) - n + 1), n // 2)
    return float(np.mean([((features.extract(x[s : s + n]) - mean) / std) @ coef + intercept for s in starts]))


def load_manifest(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["path"] = str((path.parent / r["path"]).resolve()) if not Path(r["path"]).is_absolute() else r["path"]
    return rows


def circor_manifest(root: Path) -> list[dict]:
    """CirCor DigiScope layout: <root>.csv with 'Patient ID' and 'Murmur'; audio <root>/<pid>_<site>.wav."""
    meta = root.parent / (root.name + ".csv")
    if not meta.exists():
        meta = root / "training_data.csv"
    rows = []
    with open(meta, newline="") as f:
        for r in csv.DictReader(f):
            murmur = r.get("Murmur", "").strip()
            if murmur not in ("Present", "Absent"):
                continue  # 'Unknown' excluded from binary task
            pid = r["Patient ID"].strip()
            for wav in sorted(root.glob(f"{pid}_*.wav")):
                rows.append({"path": str(wav), "patient_id": pid, "label": "1" if murmur == "Present" else "0",
                             "site": wav.stem.split("_", 1)[1], "age_group": r.get("Age", ""), "sex": r.get("Sex", ""),
                             "device": "electronic_stethoscope"})
    return rows


def synthetic_manifest(out: Path, n_patients: int = 60, seed: int = 0) -> list[dict]:
    from ..audio.synthetic import synth_pcg, to_wav_bytes

    rng = np.random.default_rng(seed)
    d = out / "synthetic_audio"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n_patients):
        label = int(i % 2)
        for k in range(2):
            x = synth_pcg(duration_s=12, sr=4000, bpm=float(rng.uniform(55, 100)), irregular=0.3 if label else 0.02,
                          noise_rms=float(rng.uniform(0.005, 0.05)), seed=i * 10 + k)
            p = d / f"p{i:03d}_{k}.wav"
            p.write_bytes(to_wav_bytes(x, 4000))
            rows.append({"path": str(p), "patient_id": f"SYN{i:03d}", "label": str(label), "device": ["stethoscope", "phone"][k]})
    return rows


def run(rows: list[dict], out: Path, seed: int = 0, synthetic: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    data = []
    for r in rows:
        audio = decode_audio(Path(r["path"]).read_bytes(), r["path"])
        q, _ = assess(audio, include_visuals=False)
        x = resample(remove_dc(audio.samples), audio.sample_rate, ANALYSIS_SR)
        data.append({**r, "x": x, "qp": q["overall"] != "unusable", "split": patient_split(r["patient_id"], seed)})

    def mat(split):
        sub = [d for d in data if d["split"] == split and d["qp"] and len(d["x"]) >= 5 * ANALYSIS_SR]
        feats = []
        for d in sub:  # window-level training examples
            n = 5 * ANALYSIS_SR
            for s in range(0, len(d["x"]) - n + 1, n // 2):
                feats.append((features.extract(d["x"][s : s + n]), int(d["label"])))
        return np.array([f for f, _ in feats]), np.array([y for _, y in feats])

    Xtr, ytr = mat("train")
    if len(set(ytr.tolist())) < 2:
        raise SystemExit("Training split needs both classes.")
    mean, std = Xtr.mean(0), Xtr.std(0) + 1e-8
    coef, intercept = fit_logreg((Xtr - mean) / std, ytr)

    val = [d for d in data if d["split"] == "val" and d["qp"]]
    vlog = np.array([recording_logit(d["x"], mean, std, coef, intercept) for d in val])
    T = fit_temperature(vlog, np.array([int(d["label"]) for d in val])) if len(val) >= 10 else 1.0

    extra_cols = sorted({k for r in rows for k in r} - {"path", "patient_id", "label"})
    with open(out / "test_predictions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recording_id", "patient_id", "label", "score", "split", "quality_pass", *extra_cols])
        for d in data:
            if d["split"] != "test":
                continue
            score = ""
            if d["qp"] and len(d["x"]) >= 5 * ANALYSIS_SR:
                score = f"{1 / (1 + np.exp(-recording_logit(d['x'], mean, std, coef, intercept) / T)):.6f}"
            w.writerow([Path(d["path"]).stem, d["patient_id"], d["label"], score, "test", int(bool(score)), *[d.get(c, "") for c in extra_cols]])
    with open(out / "training_manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["patient_id", "split"])
        for pid in sorted({(d["patient_id"], d["split"]) for d in data if d["split"] != "test"}):
            w.writerow(pid)

    name = "cardiolens-baseline-synthetic-smoke" if synthetic else "cardiolens-baseline-logreg"
    weights = {
        "features_version": features.FEATURES_VERSION, "feature_names": features.FEATURE_NAMES,
        "mean": mean.tolist(), "std": std.tolist(), "coef": coef.tolist(), "intercept": intercept, "temperature": T, "window_s": 5.0,
        "card": {
            "name": name, "version": VERSION,
            "intended_use": "Research baseline for benchmarking only. Not for clinical use."
                            + (" Trained on SYNTHETIC signals: outputs are meaningless." if synthetic else ""),
            "categories": [{"id": "negative", "label": "Negative class (per training label definition)"},
                           {"id": "positive", "label": "Positive class (per training label definition)"}],
            "validation_status": "research_only", "calibrated": False,
            "calibration_method": "temperature scaling on validation split (calibration not independently assessed)",
            "input_sample_rate": ANALYSIS_SR, "min_duration_s": 5.0,
            "training_datasets": ["synthetic"] if synthetic else [], "supported_devices": [], "supported_sites": [],
            "known_limitations": ["Hand-crafted features and a linear model; intended only as a benchmark reference."],
        },
    }
    (out / "weights.json").write_text(json.dumps(weights, indent=1))
    summary = {s: {"patients": len({d["patient_id"] for d in data if d["split"] == s}), "recordings": sum(d["split"] == s for d in data)}
               for s in ("train", "val", "test")}
    (out / "split_summary.json").write_text(json.dumps({"seed": seed, "temperature": T, "splits": summary}, indent=1))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path)
    src.add_argument("--circor-dir", type=Path)
    src.add_argument("--synthetic-smoke", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    if a.synthetic_smoke:
        print("WARNING: synthetic smoke run — verifies the pipeline only; metrics are meaningless.", file=sys.stderr)
        rows = synthetic_manifest(a.out, seed=a.seed)
    else:
        rows = load_manifest(a.manifest) if a.manifest else circor_manifest(a.circor_dir)
    print(json.dumps(run(rows, a.out, a.seed, synthetic=a.synthetic_smoke), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
