"""Model-integration contract (API version `inference/v1`).

A model is anything that implements `ModelAdapter`. The adapter declares a
`ModelCard`; the platform uses the card — not the model's own output — to
decide how a result may be labelled. Output that does not satisfy the
contract is rejected, never repaired or guessed.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Protocol

import numpy as np

CONTRACT_VERSION = "inference/v1"
VALIDATED_STATUSES = {"externally_validated"}
VALIDATION_STATUSES = {"research_only", "internally_evaluated", "externally_validated"}


class InferenceError(RuntimeError):
    """Any failure to obtain a contract-conformant result. Never yields a result."""


@dataclass
class ModelCard:
    name: str
    version: str
    intended_use: str
    categories: list[dict]  # [{"id": "abnormal", "label": "Abnormal heart sound (screening)"}]
    validation_status: str = "research_only"
    validation_evidence: str | None = None
    calibrated: bool = False
    calibration_method: str | None = None
    exclusive_categories: bool = True
    input_sample_rate: int = 2000
    min_duration_s: float = 5.0
    supported_devices: list[str] = field(default_factory=list)
    supported_sites: list[str] = field(default_factory=list)
    training_datasets: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    weights_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.validation_status not in VALIDATION_STATUSES:
            raise ValueError(f"unknown validation_status {self.validation_status!r}")
        if self.validation_status in VALIDATED_STATUSES and not self.validation_evidence:
            raise ValueError("a validated model card must cite its validation evidence")
        if not self.categories:
            raise ValueError("model card must declare its output categories")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelInput:
    samples: np.ndarray  # mono float, already at card.input_sample_rate
    sample_rate: int
    device_type: str
    auscultation_site: str
    quality_report: dict


class ModelAdapter(Protocol):
    card: ModelCard

    def predict(self, inp: ModelInput) -> dict: ...


def validate_output(card: ModelCard, out: object) -> dict:
    """Strictly validate a raw model response against the contract.

    Expected shape:
      {"abstained": bool, "abstain_reason": str|None,
       "scores": [{"category": <id>, "score": float in [0,1]}],
       "segments": [{"start_s": float, "end_s": float}]  (optional)}
    """
    if not isinstance(out, dict):
        raise InferenceError("model returned a non-object response")
    abstained = out.get("abstained", False)
    if not isinstance(abstained, bool):
        raise InferenceError("'abstained' must be boolean")
    if abstained:
        return {"abstained": True, "abstain_reason": str(out.get("abstain_reason") or "Model declined to score this recording."), "scores": [], "segments": []}

    scores = out.get("scores")
    if not isinstance(scores, list) or not scores:
        raise InferenceError("model response has no scores")
    known = {c["id"]: c for c in card.categories}
    clean, seen = [], set()
    for s in scores:
        if not isinstance(s, dict) or s.get("category") not in known:
            raise InferenceError("model returned a category not declared in its model card")
        v = s.get("score")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise InferenceError("model returned an invalid score")
        if s["category"] in seen:
            raise InferenceError("duplicate category in model response")
        seen.add(s["category"])
        clean.append({
            "category": s["category"],
            "label": known[s["category"]].get("label", s["category"]),
            "score": round(float(v), 4),
            "score_type": "calibrated_probability" if card.calibrated else "uncalibrated_score",
        })
    if seen != set(known):
        raise InferenceError("model response does not cover every declared category")
    if card.exclusive_categories and abs(sum(c["score"] for c in clean) - 1.0) > 0.02:
        raise InferenceError("scores for mutually exclusive categories do not sum to 1")

    segments = []
    for seg in out.get("segments") or []:
        try:
            a, b = float(seg["start_s"]), float(seg["end_s"])
        except (KeyError, TypeError, ValueError) as e:
            raise InferenceError("malformed segment in model response") from e
        if not (0 <= a < b):
            raise InferenceError("invalid segment bounds")
        segments.append({"start_s": round(a, 2), "end_s": round(b, 2)})
    return {"abstained": False, "abstain_reason": None, "scores": clean, "segments": segments}
