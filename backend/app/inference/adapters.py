"""Concrete model adapters.

* `HttpModelAdapter`  — calls an external, separately deployed model service
  (e.g. a PyTorch/TorchServe/Triton container). Recommended for real models.
* `LocalBaselineAdapter` — in-process logistic-regression baseline produced by
  `research/baseline/train_baseline.py`. Always `research_only`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import httpx
import numpy as np
from scipy.io import wavfile

from ..audio import features
from .base import CONTRACT_VERSION, InferenceError, ModelCard, ModelInput, validate_output


def load_card(path: Path) -> ModelCard:
    data = json.loads(Path(path).read_text())
    return ModelCard(**data)


class HttpModelAdapter:
    """POST {contract, sample_rate, audio_wav_b64, metadata} → contract response."""

    def __init__(self, url: str, card: ModelCard, timeout_s: float = 10.0, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.card = card
        self.timeout_s = timeout_s
        self._client = client

    def predict(self, inp: ModelInput) -> dict:
        buf = io.BytesIO()
        wavfile.write(buf, inp.sample_rate, inp.samples.astype(np.float32))
        payload = {
            "contract": CONTRACT_VERSION,
            "model": {"name": self.card.name, "version": self.card.version},
            "sample_rate": inp.sample_rate,
            "audio_wav_b64": base64.b64encode(buf.getvalue()).decode(),
            "metadata": {"device_type": inp.device_type, "auscultation_site": inp.auscultation_site},
        }
        client = self._client or httpx.Client(timeout=self.timeout_s)
        try:
            r = client.post(f"{self.url}/v1/predict", json=payload, timeout=self.timeout_s)
        except httpx.TimeoutException as e:
            raise InferenceError("model service timed out") from e
        except httpx.HTTPError as e:
            raise InferenceError("model service unreachable") from e
        finally:
            if self._client is None:
                client.close()
        if r.status_code != 200:
            raise InferenceError(f"model service returned HTTP {r.status_code}")
        try:
            body = r.json()
        except ValueError as e:
            raise InferenceError("model service returned invalid JSON") from e
        if body.get("model", {}).get("version") != self.card.version:
            raise InferenceError("model service version does not match the registered model card")
        return body


class LocalBaselineAdapter:
    def __init__(self, weights_path: Path):
        raw = Path(weights_path).read_bytes()
        w = json.loads(raw)
        if w.get("features_version") != features.FEATURES_VERSION:
            raise ValueError("baseline weights were trained with a different feature version")
        card = dict(w["card"])
        card["weights_sha256"] = hashlib.sha256(raw).hexdigest()
        card["validation_status"] = "research_only"  # never trust a file to self-certify
        card["validation_evidence"] = None
        self.card = ModelCard(**card)
        self.mean = np.array(w["mean"])
        self.std = np.array(w["std"])
        self.coef = np.array(w["coef"])
        self.intercept = float(w["intercept"])
        self.temperature = float(w.get("temperature", 1.0))
        self.window_s = float(w.get("window_s", 5.0))

    def predict(self, inp: ModelInput) -> dict:
        x, sr = inp.samples, inp.sample_rate
        n = int(self.window_s * sr)
        if len(x) < n:
            return {"abstained": True, "abstain_reason": "Recording shorter than the model's analysis window."}
        # Score each window and average logits (simple, reproducible aggregation).
        starts = list(range(0, len(x) - n + 1, n // 2))
        logits = []
        for s in starts:
            z = (features.extract(x[s : s + n], sr) - self.mean) / self.std
            logits.append(float(z @ self.coef + self.intercept))
        logit = float(np.mean(logits)) / self.temperature
        p = 1.0 / (1.0 + np.exp(-logit))
        pos, neg = self.card.categories[1]["id"], self.card.categories[0]["id"]
        return {
            "model": {"name": self.card.name, "version": self.card.version},
            "abstained": False,
            "scores": [{"category": neg, "score": 1 - p}, {"category": pos, "score": p}],
            "segments": [{"start_s": s / sr, "end_s": (s + n) / sr} for s in starts],
        }
