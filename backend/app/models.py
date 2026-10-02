"""Database schema. Collect only what the intended use requires (data minimisation)."""

from __future__ import annotations

import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_pseudonym() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "CL-" + "".join(secrets.choice(alphabet) for _ in range(6))


class Role(str, enum.Enum):
    clinician = "clinician"
    researcher = "researcher"
    admin = "admin"


class QualityStatus(str, enum.Enum):
    usable = "usable"
    usable_with_warnings = "usable_with_warnings"
    unusable = "unusable"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    in_review = "in_review"
    reviewed = "reviewed"
    flagged = "flagged"


class ResultTier(str, enum.Enum):
    """What kind of output an analysis carries. Never upgrade a tier implicitly."""

    signal_only = "signal_only"  # signal-quality / acoustic measurements only, no model
    experimental = "experimental"  # model output from a non-validated (research) model
    validated = "validated"  # output from a model with documented independent validation


class ModelStatus(str, enum.Enum):
    not_run_quality = "not_run_quality"  # recording failed quality gate
    no_model = "no_model"  # research-demo mode: no model configured
    service_error = "service_error"  # inference failed; no result shown
    completed = "completed"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Identity-provider subject ("iss|sub") when signing in via OIDC.
    external_subject: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    pseudonym: Mapped[str] = mapped_column(String(32), unique=True, default=new_pseudonym)
    # Optional site-local reference (e.g. MRN) — store only if the site requires linkage.
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    recordings: Mapped[list[Recording]] = relationship(back_populates="patient")


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)

    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    device_type: Mapped[str] = mapped_column(String(40), default="unknown")
    auscultation_site: Mapped[str] = mapped_column(String(40), default="unspecified")
    environment: Mapped[str] = mapped_column(String(40), default="unspecified")

    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_version: Mapped[str] = mapped_column(String(32), default="v1")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    quality_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default=ReviewStatus.pending.value)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped[Patient] = relationship(back_populates="recordings")
    analyses: Mapped[list[Analysis]] = relationship(back_populates="recording", order_by="Analysis.id")
    reviews: Mapped[list[Review]] = relationship(back_populates="recording", order_by="Review.id")


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(ForeignKey("recordings.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    pipeline_version: Mapped[str] = mapped_column(String(32))
    quality_report: Mapped[dict] = mapped_column(JSON)
    signal_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_status: Mapped[str] = mapped_column(String(32))
    result_tier: Mapped[str] = mapped_column(String(32), default=ResultTier.signal_only.value)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    recording: Mapped[Recording] = relationship(back_populates="analyses")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(ForeignKey("recordings.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    clinician_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_for_followup: Mapped[bool] = mapped_column(Boolean, default=False)

    recording: Mapped[Recording] = relationship(back_populates="reviews")
    reviewer: Mapped[User] = relationship()


class AuditEvent(Base):
    """Append-only, hash-chained audit log (tamper-evident, not tamper-proof)."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    license: Mapped[str] = mapped_column(String(200))
    permitted_use: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(Text)
    label_definitions: Mapped[str] = mapped_column(Text)
    recording_devices: Mapped[str] = mapped_column(Text, default="")
    population: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[str] = mapped_column(Text, default="")
    n_patients: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_recordings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    intended_use: Mapped[str] = mapped_column(Text)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    # research_only | internally_evaluated | externally_validated
    validation_status: Mapped[str] = mapped_column(String(40), default="research_only")
    validation_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    training_datasets: Mapped[list] = mapped_column(JSON, default=list)
    weights_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    split_name: Mapped[str] = mapped_column(String(32))
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.5)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    n_recordings: Mapped[int] = mapped_column(Integer)
    n_patients: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    model_version: Mapped[ModelVersion] = relationship()
    dataset: Mapped[Dataset] = relationship()
