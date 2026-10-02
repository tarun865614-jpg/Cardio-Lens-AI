"""Explicit response shaping. Storage keys and hashes of secrets never leave the server."""

from __future__ import annotations

from .inference.service import get_adapter
from .models import Analysis, Patient, Recording, Review, User

RESULT_TIER_TEXT = {
    "signal_only": "Signal analysis only — no AI screening result",
    "experimental": "EXPERIMENTAL model output — research use only, not for clinical decisions",
    "validated": "Screening output from an externally validated model — not a diagnosis",
}

MODEL_STATUS_TEXT = {
    "not_run_quality": "Model not run: the recording did not pass quality checks.",
    "no_model": "Research-demo mode: no validated model is configured, so no screening result is produced.",
    "service_error": "Model service error: no model result is available. Nothing has been inferred.",
    "completed": "Model analysis completed.",
}


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "org_id": u.org_id,
            "is_active": u.is_active, "is_demo": u.is_demo}


def analysis_out(a: Analysis, *, include_visuals: bool = True) -> dict:
    summary = dict(a.signal_summary or {})
    if not include_visuals:
        for k in ("waveform", "envelope", "spectrogram", "windows"):
            summary.pop(k, None)
    return {
        "id": a.id,
        "created_at": a.created_at,
        "pipeline_version": a.pipeline_version,
        "quality": a.quality_report,
        "signal_summary": summary,
        "model_status": a.model_status,
        "model_status_text": MODEL_STATUS_TEXT.get(a.model_status, a.model_status),
        "result_tier": a.result_tier,
        "result_tier_text": RESULT_TIER_TEXT[a.result_tier],
        "model_name": a.model_name,
        "model_version": a.model_version,
        "model_output": a.model_output,
        "error": a.error,
        "boundaries": [
            "This analysis is decision support for a qualified healthcare professional and is not a diagnosis.",
            "A negative or low score does not mean the heart is healthy.",
            "If the patient has severe or urgent symptoms (e.g. chest pain, fainting, severe breathlessness), "
            "follow urgent-care pathways — do not wait for or rely on this analysis.",
        ],
    }


def review_out(r: Review) -> dict:
    return {"id": r.id, "created_at": r.created_at, "status": r.status, "note": r.note,
            "clinician_conclusion": r.clinician_conclusion, "flagged_for_followup": r.flagged_for_followup,
            "reviewer": {"id": r.reviewer.id, "full_name": r.reviewer.full_name} if r.reviewer else None}


def recording_out(r: Recording, *, detail: bool = False) -> dict:
    latest = r.analyses[-1] if r.analyses else None
    out = {
        "id": r.id,
        "patient_id": r.patient_id,
        "patient_pseudonym": r.patient.pseudonym if r.patient else None,
        "created_at": r.created_at,
        "recorded_at": r.recorded_at,
        "original_filename": r.original_filename,
        "content_type": r.content_type,
        "size_bytes": r.size_bytes,
        "sha256": r.sha256,
        "sample_rate": r.sample_rate,
        "channels": r.channels,
        "duration_s": r.duration_s,
        "device_type": r.device_type,
        "auscultation_site": r.auscultation_site,
        "environment": r.environment,
        "is_demo": r.is_demo,
        "consent_confirmed": r.consent_confirmed,
        "quality_status": r.quality_status,
        "review_status": r.review_status,
        "retention_until": r.retention_until,
        "audio_available": r.storage_key is not None and r.deleted_at is None,
        "deleted_at": r.deleted_at,
        "latest_result_tier": latest.result_tier if latest else None,
        "latest_model_status": latest.model_status if latest else None,
    }
    if detail:
        out["analyses"] = [analysis_out(a, include_visuals=(a is latest)) for a in r.analyses]
        out["reviews"] = [review_out(v) for v in r.reviews]
    return out


def patient_out(p: Patient, *, detail: bool = False) -> dict:
    live = [r for r in p.recordings if r.deleted_at is None]
    out = {"id": p.id, "pseudonym": p.pseudonym, "external_ref": p.external_ref, "birth_year": p.birth_year, "sex": p.sex,
           "is_synthetic": p.is_synthetic, "created_at": p.created_at, "recording_count": len(live),
           "last_recording_at": max((r.created_at for r in live), default=None),
           "open_reviews": sum(1 for r in live if r.review_status in ("pending", "in_review", "flagged"))}
    if detail:
        out["recordings"] = [recording_out(r) for r in sorted(p.recordings, key=lambda r: r.created_at, reverse=True)]
    return out


def system_mode() -> dict:
    try:
        adapter = get_adapter()
    except Exception as e:
        return {"mode": "model_error", "label": "Model configuration error", "detail": str(e), "model": None}
    if adapter is None:
        return {"mode": "research_demo", "label": "Research-demo mode",
                "detail": "No validated model is configured. The platform shows signal-quality and acoustic measurements only.",
                "model": None}
    c = adapter.card
    validated = c.validation_status == "externally_validated"
    return {"mode": "validated_model" if validated else "experimental_model",
            "label": "Validated screening model" if validated else "Experimental model (research use only)",
            "detail": c.intended_use,
            "model": {"name": c.name, "version": c.version, "validation_status": c.validation_status, "calibrated": c.calibrated}}
