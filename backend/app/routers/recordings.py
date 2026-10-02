import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..audio.decode import AudioDecodeError, decode_audio
from ..config import get_settings
from ..database import get_db
from ..inference.service import analyze
from ..models import Analysis, Organization, Recording, Review, ReviewStatus, User
from ..reports import build_report, render_report_html
from ..security import CLINICAL, require_roles
from ..serializers import recording_out, review_out
from ..storage import StorageError, get_storage
from .patients import get_patient

router = APIRouter(tags=["recordings"])

DEVICE_TYPES = {"electronic_stethoscope", "smartphone_mic", "external_mic", "other", "unknown"}
SITES = {"aortic", "pulmonic", "tricuspid", "mitral", "other", "unspecified"}
ENVIRONMENTS = {"clinic_quiet", "clinic_busy", "home", "ward", "other", "unspecified"}
ALLOWED_CT_PREFIXES = ("audio/", "video/webm", "application/octet-stream")


def get_recording(db: Session, user: User, recording_id: int, *, allow_deleted: bool = False) -> Recording:
    r = db.scalar(
        select(Recording)
        .options(selectinload(Recording.analyses), selectinload(Recording.reviews).selectinload(Review.reviewer), selectinload(Recording.patient))
        .where(Recording.id == recording_id, Recording.org_id == user.org_id)
    )
    if r is None or (r.deleted_at is not None and not allow_deleted):
        raise HTTPException(404, "Recording not found")
    return r


def _store_analysis(db: Session, rec: Recording, outcome) -> Analysis:
    a = Analysis(recording_id=rec.id, pipeline_version=outcome.pipeline_version, quality_report=outcome.quality_report,
                 signal_summary=outcome.signal_summary, model_status=outcome.model_status, result_tier=outcome.result_tier,
                 model_name=outcome.model_name, model_version=outcome.model_version, model_output=outcome.model_output, error=outcome.error)
    db.add(a)
    rec.quality_status = outcome.quality_report["overall"]
    return a


@router.post("/patients/{patient_id}/recordings", status_code=201)
async def upload_recording(
    patient_id: int,
    file: UploadFile = File(...),
    consent_confirmed: bool = Form(...),
    device_type: str = Form("unknown"),
    auscultation_site: str = Form("unspecified"),
    environment: str = Form("unspecified"),
    recorded_at: datetime | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLINICAL)),
):
    if not consent_confirmed:
        raise HTTPException(422, "Recording consent must be confirmed before audio can be stored.")
    if device_type not in DEVICE_TYPES or auscultation_site not in SITES or environment not in ENVIRONMENTS:
        raise HTTPException(422, "Invalid device type, auscultation site or environment")
    ct = (file.content_type or "application/octet-stream").lower()
    if not ct.startswith(ALLOWED_CT_PREFIXES):
        raise HTTPException(415, "Only audio files are accepted")

    patient = get_patient(db, user, patient_id)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds the {get_settings().max_upload_mb} MB limit")

    try:
        audio = decode_audio(data, file.filename)
    except AudioDecodeError as e:
        audit.record(db, user, "recording.rejected", "patient", patient.id, {"reason": str(e)})
        db.commit()
        raise HTTPException(422, {"code": "invalid_audio", "message": str(e), "recommend_rerecord": True})

    org = db.get(Organization, user.org_id)
    key = get_storage().put(data)
    rec = Recording(
        org_id=user.org_id, patient_id=patient.id, uploaded_by=user.id,
        recorded_at=recorded_at, original_filename=(file.filename or "recording")[:255], content_type=ct[:100],
        storage_key=key, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
        sample_rate=audio.sample_rate, channels=audio.channels, duration_s=round(audio.duration_s, 3),
        device_type=device_type, auscultation_site=auscultation_site, environment=environment,
        consent_confirmed=True, is_demo=patient.is_synthetic,
        retention_until=datetime.now(timezone.utc) + timedelta(days=org.retention_days if org else 365),
    )
    db.add(rec)
    db.flush()
    outcome = analyze(audio, device_type=device_type, auscultation_site=auscultation_site)
    _store_analysis(db, rec, outcome)
    audit.record(db, user, "recording.upload", "recording", rec.id,
                 {"patient": patient.pseudonym, "sha256": rec.sha256, "quality": outcome.quality_report["overall"],
                  "model_status": outcome.model_status, "result_tier": outcome.result_tier})
    db.commit()
    return recording_out(get_recording(db, user, rec.id), detail=True)


@router.get("/recordings")
def list_recordings(review_status: str | None = None, quality_status: str | None = None, patient_id: int | None = None,
                    limit: int = Query(100, le=500), db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    stmt = (select(Recording).options(selectinload(Recording.patient), selectinload(Recording.analyses))
            .where(Recording.org_id == user.org_id, Recording.deleted_at.is_(None))
            .order_by(Recording.created_at.desc()).limit(limit))
    if review_status:
        stmt = stmt.where(Recording.review_status == review_status)
    if quality_status:
        stmt = stmt.where(Recording.quality_status == quality_status)
    if patient_id:
        stmt = stmt.where(Recording.patient_id == patient_id)
    return [recording_out(r) for r in db.scalars(stmt)]


@router.get("/recordings/{recording_id}")
def read_recording(recording_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    r = get_recording(db, user, recording_id)
    audit.record(db, user, "recording.view", "recording", r.id)
    db.commit()
    return recording_out(r, detail=True)


@router.get("/recordings/{recording_id}/audio")
def recording_audio(recording_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    r = get_recording(db, user, recording_id)
    if not r.storage_key:
        raise HTTPException(410, "Audio has been deleted")
    try:
        data = get_storage().get(r.storage_key)
    except StorageError as e:
        raise HTTPException(500, f"Audio unavailable: {e}")
    if hashlib.sha256(data).hexdigest() != r.sha256:
        raise HTTPException(500, "Audio integrity check failed")
    audit.record(db, user, "recording.audio_access", "recording", r.id)
    db.commit()
    return Response(content=data, media_type=r.content_type if r.content_type.startswith("audio/") else "audio/wav",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


@router.post("/recordings/{recording_id}/reanalyze")
def reanalyze(recording_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    r = get_recording(db, user, recording_id)
    if not r.storage_key:
        raise HTTPException(410, "Audio has been deleted")
    audio = decode_audio(get_storage().get(r.storage_key), r.original_filename)
    outcome = analyze(audio, device_type=r.device_type, auscultation_site=r.auscultation_site)
    _store_analysis(db, r, outcome)
    audit.record(db, user, "recording.reanalyze", "recording", r.id,
                 {"model_status": outcome.model_status, "result_tier": outcome.result_tier, "model_version": outcome.model_version})
    db.commit()
    db.expire_all()
    return recording_out(get_recording(db, user, r.id), detail=True)


@router.delete("/recordings/{recording_id}")
def delete_recording(recording_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    r = get_recording(db, user, recording_id)
    destroyed = get_storage().delete(r.storage_key) if r.storage_key else False
    r.storage_key = None
    r.deleted_at = datetime.now(timezone.utc)
    audit.record(db, user, "recording.delete", "recording", r.id, {"audio_destroyed": destroyed})
    db.commit()
    return {"deleted": True, "audio_destroyed": destroyed}


class ReviewIn(BaseModel):
    status: ReviewStatus
    note: str = Field(default="", max_length=10000)
    clinician_conclusion: str | None = Field(default=None, max_length=10000)
    flagged_for_followup: bool = False


@router.post("/recordings/{recording_id}/reviews", status_code=201)
def add_review(recording_id: int, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    r = get_recording(db, user, recording_id)
    status = ReviewStatus.flagged.value if body.flagged_for_followup else body.status.value
    v = Review(recording_id=r.id, reviewer_id=user.id, status=status, note=body.note,
               clinician_conclusion=body.clinician_conclusion, flagged_for_followup=body.flagged_for_followup)
    db.add(v)
    prev = r.review_status
    r.review_status = status
    db.flush()
    audit.record(db, user, "review.create", "recording", r.id, {"from": prev, "to": status, "flagged": body.flagged_for_followup, "review_id": v.id})
    db.commit()
    db.refresh(v)
    return review_out(v)


@router.get("/recordings/{recording_id}/report")
def report(recording_id: int, format: str = Query("json", pattern="^(json|html)$"), db: Session = Depends(get_db),
           user: User = Depends(require_roles(*CLINICAL))):
    r = get_recording(db, user, recording_id)
    rep = build_report(r, user)
    audit.record(db, user, "report.export", "recording", r.id, {"format": format, "report_id": rep["report_id"]})
    db.commit()
    if format == "html":
        return HTMLResponse(render_report_html(rep), headers={
            "Content-Disposition": f'attachment; filename="cardiolens-report-{r.patient.pseudonym}-{r.id}.html"',
            "Cache-Control": "no-store"})
    return rep
