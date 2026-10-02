"""Hash-chained audit trail. Every write to clinical data goes through `record`."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditEvent, User, utcnow

GENESIS = "0" * 64


def _aware(ts: datetime) -> datetime:
    # SQLite drops tzinfo on read; all timestamps are stored as UTC.
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _digest(prev_hash: str, payload: dict) -> str:
    blob = prev_hash + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def record(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: object = None,
    details: dict | None = None,
    org_id: int | None = None,
) -> AuditEvent:
    if db.get_bind().dialect.name == "postgresql":
        # Serialise chain appends across workers/instances for this transaction.
        db.execute(text("SELECT pg_advisory_xact_lock(724100)"))
    last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
    prev = last.hash if last else GENESIS
    ts = utcnow()
    payload = {
        "ts": ts.isoformat(),
        "org_id": org_id if org_id is not None else (actor.org_id if actor else None),
        "actor_id": actor.id if actor else None,
        "action": action,
        "entity_type": entity_type,
        "entity_id": None if entity_id is None else str(entity_id),
        "details": details or {},
    }
    ev = AuditEvent(
        ts=ts,
        org_id=payload["org_id"],
        actor_id=payload["actor_id"],
        actor_email=actor.email if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=payload["entity_id"],
        details=payload["details"],
        prev_hash=prev,
        hash=_digest(prev, payload),
    )
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Recompute the chain. Returns (ok, first_bad_event_id)."""
    prev = GENESIS
    for ev in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        ts = _aware(ev.ts).isoformat()
        payload = {
            "ts": ts,
            "org_id": ev.org_id,
            "actor_id": ev.actor_id,
            "action": ev.action,
            "entity_type": ev.entity_type,
            "entity_id": ev.entity_id,
            "details": ev.details,
        }
        if ev.prev_hash != prev or ev.hash != _digest(prev, payload):
            return False, ev.id
        prev = ev.hash
    return True, None
