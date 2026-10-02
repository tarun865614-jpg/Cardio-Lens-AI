"""Evaluation-run ingestion with methodological guard-rails.

Input: a CSV of per-recording predictions on held-out data with columns
    recording_id, patient_id, label, score, split, quality_pass
and optional columns
    device, environment, site, age_group, sex, <any other subgroup column>
plus an optional *training manifest* (patient IDs used for training/tuning).

Guard-rails (hard errors, the run is refused):
  * rows whose split is 'train' or 'val'/'tuning' — final metrics must use test data
  * any test patient appearing in the training manifest (patient-level leakage)
  * any patient appearing in more than one split within the file
  * labels not in {0,1}, scores outside [0,1]
Soft warnings are stored alongside the metrics (small n, single-site data, etc.).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict

import numpy as np

from .metrics import binary_metrics, wilson

REQUIRED = ["recording_id", "patient_id", "label", "score", "split", "quality_pass"]
TEST_SPLITS = {"test", "holdout", "external"}
NON_TEST = {"train", "training", "val", "valid", "validation", "tuning", "dev"}
CORE_COLS = set(REQUIRED)
MIN_SUBGROUP_N = 30


class EvaluationError(ValueError):
    pass


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "pass"}


def parse_predictions(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise EvaluationError("CSV is empty")
    missing = [c for c in REQUIRED if c not in reader.fieldnames]
    if missing:
        raise EvaluationError(f"CSV missing required columns: {', '.join(missing)}")
    rows = list(reader)
    if not rows:
        raise EvaluationError("CSV has no rows")
    return rows


def evaluate(text: str, *, threshold: float = 0.5, training_patients: set[str] | None = None,
             is_external: bool = False, n_boot: int = 1000) -> dict:
    rows = parse_predictions(text)
    splits = {r["split"].strip().lower() for r in rows}
    bad = splits & NON_TEST
    if bad:
        raise EvaluationError(f"Rows from non-test split(s) {sorted(bad)} found. Final metrics must be computed on held-out test data only.")
    unknown = splits - TEST_SPLITS
    if unknown:
        raise EvaluationError(f"Unknown split value(s) {sorted(unknown)}; use one of {sorted(TEST_SPLITS)}.")

    patient_splits = defaultdict(set)
    for r in rows:
        patient_splits[r["patient_id"].strip()].add(r["split"].strip().lower())
    multi = [p for p, s in patient_splits.items() if len(s) > 1]
    if multi:
        raise EvaluationError(f"{len(multi)} patient(s) appear in more than one split (e.g. {multi[0]}).")
    if training_patients:
        leaked = sorted(set(patient_splits) & training_patients)
        if leaked:
            raise EvaluationError(f"Patient-level leakage: {len(leaked)} test patient(s) also appear in the training manifest (e.g. {leaked[0]}).")

    recs, seen = [], set()
    for i, r in enumerate(rows, start=2):
        rid = r["recording_id"].strip()
        if rid in seen:
            raise EvaluationError(f"Duplicate recording_id {rid!r}")
        seen.add(rid)
        qp = _truthy(r["quality_pass"])
        lab = r["label"].strip()
        if lab not in {"0", "1"}:
            raise EvaluationError(f"Row {i}: label must be 0 or 1")
        score = None
        if qp:
            try:
                score = float(r["score"])
            except ValueError:
                raise EvaluationError(f"Row {i}: score is not a number")
            if not 0 <= score <= 1:
                raise EvaluationError(f"Row {i}: score outside [0, 1]")
        recs.append({**r, "_qp": qp, "_y": int(lab), "_s": score, "_pid": r["patient_id"].strip()})

    warnings: list[str] = []
    if training_patients is None:
        warnings.append("No training manifest supplied: patient-level leakage against the training set could not be checked.")
    if not is_external:
        warnings.append("Internal held-out evaluation only. External validation on an independent dataset is still required.")

    def block(subset: list[dict]) -> dict:
        n_all = len(subset)
        failed = sum(1 for r in subset if not r["_qp"])
        ok = [r for r in subset if r["_qp"]]
        res = {
            "n_recordings": n_all,
            "n_patients": len({r["_pid"] for r in subset}),
            "failed_recording_rate": wilson(failed, n_all),
        }
        if ok:
            res.update(binary_metrics([r["_y"] for r in ok], [r["_s"] for r in ok], [r["_pid"] for r in ok], threshold, n_boot=n_boot))
        else:
            res["reason"] = "no recordings passed quality"
        return res

    overall = block(recs)
    if overall["n_recordings"] < 100:
        warnings.append(f"Small evaluation set (n={overall['n_recordings']}); confidence intervals are wide.")

    subgroup_cols = [c for c in rows[0].keys() if c not in CORE_COLS and c not in {"notes"}]
    subgroups: dict[str, dict] = {}
    for col in subgroup_cols:
        groups = defaultdict(list)
        for r in recs:
            v = (r.get(col) or "").strip()
            if v:
                groups[v].append(r)
        if len(groups) < 2:
            continue
        subgroups[col] = {}
        for v, sub in sorted(groups.items()):
            entry = block(sub)
            for heavy in ("roc", "calibration"):
                entry.pop(heavy, None)
            if len(sub) < MIN_SUBGROUP_N:
                entry["warning"] = f"n < {MIN_SUBGROUP_N}: estimate unreliable"
            subgroups[col][v] = entry
    if not any(c in subgroups for c in ("device", "environment")):
        warnings.append("No device/environment breakdown available: performance across recording conditions is not evaluated.")

    return {"overall": overall, "subgroups": subgroups, "warnings": warnings,
            "n_recordings": overall["n_recordings"], "n_patients": overall["n_patients"]}
