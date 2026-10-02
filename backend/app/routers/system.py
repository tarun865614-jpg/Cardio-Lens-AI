from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..audio.decode import ffmpeg_available
from ..audio.quality import PIPELINE_VERSION
from ..database import get_db
from ..inference.base import CONTRACT_VERSION
from ..models import Patient, Recording, User
from ..security import CLINICAL, current_user, require_roles
from ..serializers import recording_out, system_mode

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system/status")
def status(user: User = Depends(current_user)):
    return {"mode": system_mode(), "quality_pipeline": PIPELINE_VERSION, "inference_contract": CONTRACT_VERSION,
            "ffmpeg_available": ffmpeg_available(), "api_version": "v1"}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    base = select(Recording).options(selectinload(Recording.patient), selectinload(Recording.analyses)).where(
        Recording.org_id == user.org_id, Recording.deleted_at.is_(None))
    recent = list(db.scalars(base.order_by(Recording.created_at.desc()).limit(8)))
    pending = list(db.scalars(base.where(Recording.review_status.in_(["pending", "in_review"])).order_by(Recording.created_at.desc()).limit(8)))
    flagged = list(db.scalars(base.where(Recording.review_status == "flagged").order_by(Recording.created_at.desc()).limit(8)))
    quality = list(db.scalars(base.where(Recording.quality_status == "unusable").order_by(Recording.created_at.desc()).limit(8)))

    def count(*conds):
        return db.scalar(select(func.count(Recording.id)).where(Recording.org_id == user.org_id, Recording.deleted_at.is_(None), *conds))

    return {
        "counts": {
            "patients": db.scalar(select(func.count(Patient.id)).where(Patient.org_id == user.org_id, Patient.deleted_at.is_(None))),
            "recordings": count(),
            "pending_review": count(Recording.review_status.in_(["pending", "in_review"])),
            "flagged": count(Recording.review_status == "flagged"),
            "quality_unusable": count(Recording.quality_status == "unusable"),
            "quality_warnings": count(Recording.quality_status == "usable_with_warnings"),
        },
        "recent": [recording_out(r) for r in recent],
        "pending_reviews": [recording_out(r) for r in pending],
        "flagged": [recording_out(r) for r in flagged],
        "quality_issues": [recording_out(r) for r in quality],
        "system": system_mode(),
    }
