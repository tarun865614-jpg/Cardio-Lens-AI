from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import AuditEvent, Organization, Recording, Role, User
from ..security import ADMIN, hash_password, require_roles
from ..serializers import user_out
from ..storage import get_storage

router = APIRouter(prefix="/admin", tags=["admin"])


class UserIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(max_length=200)
    role: Role
    # Required for local auth; omitted in OIDC mode (the IdP holds credentials).
    password: str | None = Field(default=None, min_length=12, max_length=200)


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    unlock: bool = False


class OrgSettingsIn(BaseModel):
    retention_days: int = Field(ge=30, le=3650)


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    return [user_out(u) for u in db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "Email already in use")
    oidc = get_settings().auth_mode == "oidc"
    if not oidc and not body.password:
        raise HTTPException(422, "A password of at least 12 characters is required")
    u = User(org_id=user.org_id, email=body.email.lower(), full_name=body.full_name, role=body.role.value,
             password_hash="!sso-only" if oidc else hash_password(body.password))
    db.add(u)
    db.flush()
    audit.record(db, user, "user.create", "user", u.id, {"role": u.role})
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    u = db.get(User, user_id)
    if u is None or u.org_id != user.org_id:
        raise HTTPException(404, "User not found")
    if u.id == user.id and (body.is_active is False or (body.role and body.role != Role.admin)):
        raise HTTPException(400, "Administrators cannot demote or deactivate themselves")
    changes = {}
    if body.role is not None:
        changes["role"] = [u.role, body.role.value]
        u.role = body.role.value
    if body.is_active is not None:
        changes["is_active"] = [u.is_active, body.is_active]
        u.is_active = body.is_active
    if body.unlock:
        changes["unlocked"] = True
        u.locked_until = None
        u.failed_logins = 0
    audit.record(db, user, "user.update", "user", u.id, changes)
    db.commit()
    return user_out(u)


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    org = db.get(Organization, user.org_id)
    return {"organization": org.name, "retention_days": org.retention_days}


@router.put("/settings")
def put_settings(body: OrgSettingsIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    org = db.get(Organization, user.org_id)
    audit.record(db, user, "settings.update", "organization", org.id, {"retention_days": [org.retention_days, body.retention_days]})
    org.retention_days = body.retention_days
    db.commit()
    return {"organization": org.name, "retention_days": org.retention_days}


@router.post("/retention/purge")
def purge_expired(db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    """Destroy audio past its retention date (run from a scheduled job in production)."""
    now = datetime.now(timezone.utc)
    storage = get_storage()
    n = 0
    for r in db.scalars(select(Recording).where(Recording.org_id == user.org_id, Recording.storage_key.is_not(None))):
        until = r.retention_until if r.retention_until is None or r.retention_until.tzinfo else r.retention_until.replace(tzinfo=timezone.utc)
        if until and until < now:
            storage.delete(r.storage_key)
            r.storage_key = None
            r.deleted_at = now
            n += 1
    audit.record(db, user, "retention.purge", "organization", user.org_id, {"recordings_purged": n})
    db.commit()
    return {"recordings_purged": n}


@router.get("/audit")
def list_audit(limit: int = Query(200, le=1000), action: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(require_roles(*ADMIN))):
    stmt = select(AuditEvent).where(AuditEvent.org_id == user.org_id).order_by(AuditEvent.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    return [{"id": e.id, "ts": e.ts, "actor": e.actor_email, "action": e.action, "entity_type": e.entity_type,
             "entity_id": e.entity_id, "details": e.details, "hash": e.hash} for e in db.scalars(stmt)]


@router.get("/audit/verify")
def verify_audit(db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    ok, bad = audit.verify_chain(db)
    return {"intact": ok, "first_bad_event_id": bad}
