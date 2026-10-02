from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import User
from ..oidc import public_config
from ..security import create_token, current_user, verify_password
from ..serializers import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def _aware(ts: datetime | None) -> datetime | None:
    return ts if ts is None or ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@router.get("/config")
def auth_config():
    """Public: tells the SPA whether to show the password form or start SSO."""
    return public_config()


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    s = get_settings()
    if s.auth_mode != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Password sign-in is disabled; use single sign-on")
    now = datetime.now(timezone.utc)
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))

    if user is not None and _aware(user.locked_until) and _aware(user.locked_until) > now:
        audit.record(db, None, "auth.login_locked", "user", user.id, {"email": email[:320]}, org_id=user.org_id)
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again later or contact an administrator.")

    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        details = {"email": email[:320]}
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= s.login_max_failures:
                user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
                user.failed_logins = 0
                details["locked_until"] = user.locked_until.isoformat()
        audit.record(db, None, "auth.login_failed", "user", user.id if user else None, details, org_id=user.org_id if user else None)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    audit.record(db, user, "auth.login", "user", user.id)
    db.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
