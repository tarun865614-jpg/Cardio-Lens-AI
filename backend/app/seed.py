"""Development seed: one demo organisation, three role accounts, synthetic patients and
synthetic demo recordings. Everything is flagged `is_synthetic` / `is_demo`.
Refused in production by `Settings.validate_for_runtime`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .audio.decode import decode_audio
from .audio.synthetic import synth_pcg, to_wav_bytes
from .inference.service import analyze
from .models import Analysis, Dataset, Organization, Patient, Recording, Review, User
from .security import hash_password
from .storage import get_storage

DEMO_PASSWORD = "demo-password-123"
DEMO_USERS = [
    ("clinician@demo.cardiolens.local", "Dr. Demo Clinician", "clinician"),
    ("researcher@demo.cardiolens.local", "Demo Researcher", "researcher"),
    ("admin@demo.cardiolens.local", "Demo Administrator", "admin"),
]

CANDIDATE_DATASETS = [
    dict(
        name="PhysioNet/CinC Challenge 2016 (heart sound classification)",
        source_url="https://physionet.org/content/challenge-2016/",
        license="VERIFY on source page before download",
        permitted_use="Candidate for research model development. Confirm licence terms and attribution requirements before use.",
        provenance="Multi-source collection of PCG recordings from several research groups, assembled for the 2016 PhysioNet/CinC Challenge.",
        label_definitions="Recording-level normal vs abnormal labels (plus signal-quality annotations). Abnormal is heterogeneous across sources.",
        recording_devices="Various stethoscopes/sensors depending on contributing source; not smartphone microphones.",
        population="Mixed adult and paediatric, healthy and pathological, varying by source subset.",
        limitations="Patient identifiers are not available for every subset, which limits patient-level splitting; label definitions differ across subsets.",
    ),
    dict(
        name="CirCor DigiScope Phonocardiogram Dataset (PhysioNet 2022)",
        source_url="https://physionet.org/content/circor-heart-sound/",
        license="VERIFY on source page before download",
        permitted_use="Candidate for research model development (murmur detection). Confirm licence terms before use.",
        provenance="Paediatric screening campaigns in Brazil; multiple auscultation locations per patient.",
        label_definitions="Patient-level murmur present/absent/unknown with expert annotations; clinical outcome labels.",
        recording_devices="Electronic stethoscope (single device family).",
        population="Predominantly paediatric population from one region.",
        limitations="Single-region paediatric cohort; results may not transfer to adults, other devices or smartphone recordings.",
    ),
]


def _ensure_org(db: Session) -> Organization:
    org = db.scalar(select(Organization).where(Organization.name == "Demo Research Clinic"))
    if org is None:
        org = Organization(name="Demo Research Clinic", retention_days=365)
        db.add(org)
        db.flush()
    return org


DEMO_RECORDINGS = [
    # (label, generator kwargs, device, site, env, post-process)
    ("clean", dict(bpm=68, seed=1), "electronic_stethoscope", "mitral", "clinic_quiet", None),
    ("irregular", dict(bpm=95, irregular=0.35, seed=2), "electronic_stethoscope", "aortic", "clinic_quiet", None),
    ("noisy", dict(bpm=80, noise_rms=0.25, seed=3), "smartphone_mic", "mitral", "home", None),
    ("clipped", dict(bpm=72, amplitude=3.0, seed=4), "smartphone_mic", "tricuspid", "clinic_busy", "clip"),
    ("short", dict(bpm=70, duration_s=7, seed=5), "electronic_stethoscope", "pulmonic", "ward", None),
    ("noise_only", None, "smartphone_mic", "unspecified", "home", None),
]


def seed(db: Session) -> None:
    if db.scalar(select(User).where(User.email == DEMO_USERS[0][0])):
        return
    org = _ensure_org(db)
    users = {}
    for email, name, role in DEMO_USERS:
        u = User(org_id=org.id, email=email, full_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD), is_demo=True)
        db.add(u)
        users[role] = u
    db.flush()
    clin = users["clinician"]

    for d in CANDIDATE_DATASETS:
        if not db.scalar(select(Dataset).where(Dataset.name == d["name"])):
            db.add(Dataset(**d))

    storage = get_storage()
    now = datetime.now(timezone.utc)
    rng = np.random.default_rng(42)
    for i, (label, kw, device, site, env, post) in enumerate(DEMO_RECORDINGS):
        p = Patient(org_id=org.id, created_by=clin.id, is_synthetic=True, birth_year=int(rng.integers(1940, 2005)),
                    sex=["female", "male"][i % 2])
        db.add(p)
        db.flush()
        sr = 4000
        x = synth_pcg(sr=sr, **kw) if kw else rng.normal(0, 0.1, sr * 20)
        if post == "clip":
            x = np.clip(x, -1, 1)
        data = to_wav_bytes(x, sr)
        audio = decode_audio(data, "demo.wav")
        rec = Recording(org_id=org.id, patient_id=p.id, uploaded_by=clin.id, recorded_at=now - timedelta(days=6 - i, hours=i),
                        original_filename=f"DEMO-synthetic-{label}.wav", content_type="audio/wav", storage_key=storage.put(data),
                        sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), sample_rate=sr, channels=1,
                        duration_s=round(audio.duration_s, 3), device_type=device, auscultation_site=site, environment=env,
                        consent_confirmed=True, consent_version="demo", is_demo=True, retention_until=now + timedelta(days=org.retention_days))
        db.add(rec)
        db.flush()
        o = analyze(audio, device_type=device, auscultation_site=site, use_configured=False)
        db.add(Analysis(recording_id=rec.id, pipeline_version=o.pipeline_version, quality_report=o.quality_report,
                        signal_summary=o.signal_summary, model_status=o.model_status, result_tier=o.result_tier))
        rec.quality_status = o.quality_report["overall"]
        if label == "irregular":
            db.add(Review(recording_id=rec.id, reviewer_id=clin.id, status="flagged", flagged_for_followup=True,
                          note="DEMO NOTE: irregular spacing audible on playback; refer for formal assessment.",
                          clinician_conclusion="DEMO: refer for ECG and in-person auscultation."))
            rec.review_status = "flagged"
    audit.record(db, None, "system.seed_demo", "organization", org.id, {"synthetic": True}, org_id=org.id)
    db.commit()
