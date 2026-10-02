"""Analysis orchestration:

    decode → validate → quality gate → preprocess → model inference → result labelling

Invariants (enforced here and covered by tests):
  1. A recording that fails the quality gate is never sent to a model.
  2. No configured model → `no_model` / `signal_only`; nothing resembling a
     diagnosis is produced.
  3. Any inference error, timeout or contract violation → `service_error`
     with `model_output = None`. There is no fallback result.
  4. `validated` tier requires a card with documented external validation AND
     a recording within the card's declared intended-use conditions.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
from dataclasses import dataclass

from ..audio.decode import DecodedAudio
from ..audio.preprocess import remove_dc, resample
from ..audio.quality import PIPELINE_VERSION, assess
from ..config import get_settings
from ..models import ModelStatus, ResultTier
from .base import VALIDATED_STATUSES, InferenceError, ModelAdapter, ModelInput, validate_output

log = logging.getLogger("cardiolens.inference")

_adapter: ModelAdapter | None = None
_adapter_loaded = False
_pool = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="infer")


def build_adapter_from_settings() -> ModelAdapter | None:
    s = get_settings()
    if s.model_backend == "none":
        return None
    if s.model_backend == "http":
        from .adapters import HttpModelAdapter, load_card

        if not (s.model_service_url and s.model_card_path):
            raise RuntimeError("model_backend=http requires CARDIOLENS_MODEL_SERVICE_URL and CARDIOLENS_MODEL_CARD_PATH")
        return HttpModelAdapter(s.model_service_url, load_card(s.model_card_path), s.model_service_timeout_s)
    if s.model_backend == "local_baseline":
        from .adapters import LocalBaselineAdapter

        if not s.model_card_path:
            raise RuntimeError("model_backend=local_baseline requires CARDIOLENS_MODEL_CARD_PATH (weights JSON)")
        return LocalBaselineAdapter(s.model_card_path)
    raise RuntimeError(f"unknown model_backend {s.model_backend!r}")


def get_adapter() -> ModelAdapter | None:
    global _adapter, _adapter_loaded
    if not _adapter_loaded:
        _adapter = build_adapter_from_settings()
        _adapter_loaded = True
    return _adapter


def set_adapter(adapter: ModelAdapter | None) -> None:
    """Used by tests and by admin hot-swap of model versions."""
    global _adapter, _adapter_loaded
    _adapter, _adapter_loaded = adapter, True


@dataclass
class AnalysisOutcome:
    pipeline_version: str
    quality_report: dict
    signal_summary: dict | None
    model_status: str
    result_tier: str
    model_name: str | None = None
    model_version: str | None = None
    model_output: dict | None = None
    error: str | None = None


def _within_intended_use(card, device_type: str, site: str) -> list[str]:
    issues = []
    if card.supported_devices and device_type not in card.supported_devices:
        issues.append(f"Recording device '{device_type}' is outside the model's validated devices ({', '.join(card.supported_devices)}).")
    if card.supported_sites and site not in card.supported_sites:
        issues.append(f"Auscultation site '{site}' is outside the model's validated sites ({', '.join(card.supported_sites)}).")
    return issues


def analyze(audio: DecodedAudio, *, device_type: str, auscultation_site: str, adapter: ModelAdapter | None = None, use_configured: bool = True) -> AnalysisOutcome:
    quality, summary = assess(audio)
    base = dict(pipeline_version=PIPELINE_VERSION, quality_report=quality, signal_summary=summary)

    if quality["overall"] == "unusable":
        return AnalysisOutcome(**base, model_status=ModelStatus.not_run_quality.value, result_tier=ResultTier.signal_only.value)

    if adapter is None and use_configured:
        try:
            adapter = get_adapter()
        except Exception as e:  # misconfiguration must not crash uploads or fabricate output
            log.exception("model adapter failed to load")
            return AnalysisOutcome(**base, model_status=ModelStatus.service_error.value, result_tier=ResultTier.signal_only.value,
                                   error=f"Model could not be loaded: {e}")
    if adapter is None:
        return AnalysisOutcome(**base, model_status=ModelStatus.no_model.value, result_tier=ResultTier.signal_only.value)

    card = adapter.card
    ident = dict(model_name=card.name, model_version=card.version)
    if audio.duration_s < card.min_duration_s:
        return AnalysisOutcome(**base, **ident, model_status=ModelStatus.completed.value, result_tier=ResultTier.signal_only.value,
                               model_output={"abstained": True, "abstain_reason": f"Recording shorter than the model minimum ({card.min_duration_s} s).",
                                             "scores": [], "segments": []})

    x = resample(remove_dc(audio.samples), audio.sample_rate, card.input_sample_rate)
    inp = ModelInput(samples=x, sample_rate=card.input_sample_rate, device_type=device_type, auscultation_site=auscultation_site, quality_report=quality)
    timeout = get_settings().model_service_timeout_s
    try:
        raw = _pool.submit(adapter.predict, inp).result(timeout=timeout + 1.0)
        out = validate_output(card, raw)
    except cf.TimeoutError:
        return AnalysisOutcome(**base, **ident, model_status=ModelStatus.service_error.value, result_tier=ResultTier.signal_only.value,
                               error="Model inference timed out. No model result is available for this recording.")
    except InferenceError as e:
        return AnalysisOutcome(**base, **ident, model_status=ModelStatus.service_error.value, result_tier=ResultTier.signal_only.value,
                               error=f"Model inference failed: {e}. No model result is available for this recording.")
    except Exception:
        log.exception("unexpected inference failure")
        return AnalysisOutcome(**base, **ident, model_status=ModelStatus.service_error.value, result_tier=ResultTier.signal_only.value,
                               error="Model inference failed unexpectedly. No model result is available for this recording.")

    scope_issues = _within_intended_use(card, device_type, auscultation_site)
    validated = card.validation_status in VALIDATED_STATUSES and not scope_issues and quality["overall"] == "usable"
    tier = ResultTier.validated if validated else ResultTier.experimental
    limitations = list(card.known_limitations) + scope_issues
    if quality["overall"] != "usable":
        limitations.append("Recording passed quality checks only with warnings; interpret any model output with additional caution.")
    if not card.calibrated:
        limitations.append("Model scores are not calibrated probabilities and must not be read as a likelihood of disease.")
    out.update({
        "model_card": card.to_dict(),
        "limitations": limitations,
        "tier_reason": (
            "Model has documented external validation and the recording is within its intended-use conditions."
            if validated else
            f"Model validation status is '{card.validation_status}'" + ("; recording outside intended-use conditions" if scope_issues else "")
            + ("; recording quality has warnings" if quality["overall"] != "usable" else "") + ". Output is experimental."
        ),
    })
    return AnalysisOutcome(**base, **ident, model_status=ModelStatus.completed.value, result_tier=tier.value, model_output=out)
