from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..database import get_db
from ..models import Patient, Recording, User
from ..security import ADMIN, CLINICAL, require_roles
from ..serializers import patient_out
from ..storage import get_storage

router = APIRouter(prefix="/patients", tags=["patients"])


class PatientIn(BaseModel):
    external_ref: str | None = Field(default=None, max_length=64)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    sex: str | None = Field(default=None, pattern="^(female|male|other|unknown)$")


def get_patient(db: Session, user: User, patient_id: int) -> Patient:
    p = db.scalar(
        select(Patient).options(selectinload(Patient.recordings).selectinload(Recording.analyses))
        .where(Patient.id == patient_id, Patient.org_id == user.org_id, Patient.deleted_at.is_(None))
    )
    if p is None:  # 404 (not 403) for other orgs' records: don't reveal existence
        raise HTTPException(404, "Patient not found")
    return p


@router.get("")
def list_patients(q: str | None = Query(default=None, max_length=64), has_open_reviews: bool | None = None,
                  db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    stmt = (select(Patient).options(selectinload(Patient.recordings))
            .where(Patient.org_id == user.org_id, Patient.deleted_at.is_(None)).order_by(Patient.created_at.desc()))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Patient.pseudonym.ilike(like), Patient.external_ref.ilike(like)))
    items = [patient_out(p) for p in db.scalars(stmt)]
    if has_open_reviews is not None:
        items = [p for p in items if (p["open_reviews"] > 0) == has_open_reviews]
    return items


@router.post("", status_code=201)
def create_patient(body: PatientIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    p = Patient(org_id=user.org_id, created_by=user.id, **body.model_dump())
    db.add(p)
    db.flush()
    audit.record(db, user, "patient.create", "patient", p.id, {"pseudonym": p.pseudonym})
    db.commit()
    db.refresh(p)
    return patient_out(p)


@router.get("/{patient_id}")
def read_patient(patient_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CLINICAL))):
    p = get_patient(db, user, patient_id)
    audit.record(db, user, "patient.view", "patient", p.id)
    db.commit()
    return patient_out(p, detail=True)


@router.delete("/{patient_id}")
def delete_patient(patient_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    """Erase a patient: destroys all audio objects and marks records deleted (audit trail retained)."""
    p = get_patient(db, user, patient_id)
    now = datetime.now(timezone.utc)
    storage = get_storage()
    n = 0
    for r in p.recordings:
        if r.storage_key:
            storage.delete(r.storage_key)
            r.storage_key = None
            n += 1
        r.deleted_at = r.deleted_at or now
    p.deleted_at = now
    p.external_ref = None
    audit.record(db, user, "patient.delete", "patient", p.id, {"audio_objects_destroyed": n})
    db.commit()
    return {"deleted": True, "audio_objects_destroyed": n}
