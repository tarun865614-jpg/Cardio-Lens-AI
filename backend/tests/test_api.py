"""End-to-end API workflow, permissions, isolation, deletion, reports and audit."""

import hashlib

from app.inference import service
from app.inference.base import InferenceError
from app.models import AuditEvent, Patient
from app.storage import get_storage

from .conftest import new_patient, upload, wav
from .test_inference import GOOD, FakeAdapter, card


def test_requires_authentication(client, users):
    for path in ("/api/v1/patients", "/api/v1/dashboard", "/api/v1/research/models", "/api/v1/admin/audit"):
        assert client.get(path).status_code == 401
    assert client.get("/api/v1/patients", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_login_failure_is_audited(client, users, db):
    r = client.post("/api/v1/auth/login", json={"email": "clinician@test.local", "password": "nope"})
    assert r.status_code == 401
    assert db.query(AuditEvent).filter_by(action="auth.login_failed").count() == 1


def test_full_clinical_workflow(client, auth, db):
    h = auth("clinician")
    pid = new_patient(client, h, birth_year=1970, sex="female")
    data = wav("clean")

    r = upload(client, h, pid, data)
    assert r.status_code == 201, r.text
    rec = r.json()
    a = rec["analyses"][-1]
    assert rec["quality_status"] == "usable"
    assert a["model_status"] == "no_model" and a["result_tier"] == "signal_only" and a["model_output"] is None
    assert "Research-demo mode" in a["model_status_text"]
    assert any("not mean the heart is healthy" in b for b in a["boundaries"])
    assert a["signal_summary"]["waveform"] and a["signal_summary"]["spectrogram"]

    # Original audio playback returns the exact uploaded bytes.
    audio = client.get(f"/api/v1/recordings/{rec['id']}/audio", headers=h)
    assert audio.status_code == 200 and hashlib.sha256(audio.content).hexdigest() == hashlib.sha256(data).hexdigest()
    assert audio.headers["cache-control"] == "no-store"

    # Stored at rest encrypted (no RIFF header on disk).
    p = db.get(Patient, pid)
    key = p.recordings[0].storage_key
    raw = get_storage()._path(key).read_bytes()
    assert not raw.startswith(b"RIFF") and b"WAVE" not in raw[:64]

    # Clinician review + flag.
    rv = client.post(f"/api/v1/recordings/{rec['id']}/reviews", headers=h,
                     json={"status": "reviewed", "note": "Listened; refer.", "clinician_conclusion": "Refer to cardiology", "flagged_for_followup": True})
    assert rv.status_code == 201 and rv.json()["status"] == "flagged"

    detail = client.get(f"/api/v1/recordings/{rec['id']}", headers=h).json()
    assert detail["review_status"] == "flagged" and len(detail["reviews"]) == 1

    # Reports keep automated output and clinician conclusions separate.
    rep = client.get(f"/api/v1/recordings/{rec['id']}/report", headers=h).json()
    assert rep["automated"]["model"]["status"] == "no_model"
    assert rep["clinician"]["reviews"][0]["conclusion"] == "Refer to cardiology"
    assert "conclusion" not in str(rep["automated"]).lower()
    html = client.get(f"/api/v1/recordings/{rec['id']}/report?format=html", headers=h)
    assert html.status_code == 200 and "attachment" in html.headers["content-disposition"]
    for section in ("Section A", "Section B", "Section C", "not a diagnosis"):
        assert section in html.text

    dash = client.get("/api/v1/dashboard", headers=h).json()
    assert dash["counts"]["flagged"] == 1 and dash["system"]["mode"] == "research_demo"

    # Audit trail recorded every step and the chain verifies.
    actions = {e.action for e in db.query(AuditEvent)}
    assert {"patient.create", "recording.upload", "recording.audio_access", "review.create", "report.export"} <= actions
    ha = auth("admin")
    assert client.get("/api/v1/admin/audit/verify", headers=ha).json()["intact"] is True


def test_unusable_recording_asks_for_rerecord_and_skips_model(client, auth):
    adapter = FakeAdapter(card(), GOOD)
    service.set_adapter(adapter)
    h = auth("clinician")
    pid = new_patient(client, h)
    rec = upload(client, h, pid, wav("clipped")).json()
    a = rec["analyses"][-1]
    assert rec["quality_status"] == "unusable" and a["quality"]["recommend_rerecord"]
    assert a["model_status"] == "not_run_quality" and adapter.calls == 0


def test_model_service_error_is_reported_not_fabricated(client, auth):
    service.set_adapter(FakeAdapter(card(), exc=InferenceError("connection refused")))
    h = auth("clinician")
    pid = new_patient(client, h)
    a = upload(client, h, pid, wav()).json()["analyses"][-1]
    assert a["model_status"] == "service_error" and a["model_output"] is None and a["result_tier"] == "signal_only"
    st = client.get("/api/v1/system/status", headers=h).json()
    assert st["mode"]["mode"] == "experimental_model"


def test_experimental_model_labelled(client, auth):
    service.set_adapter(FakeAdapter(card(), GOOD))
    h = auth("clinician")
    pid = new_patient(client, h)
    a = upload(client, h, pid, wav()).json()["analyses"][-1]
    assert a["result_tier"] == "experimental" and a["result_tier_text"].startswith("EXPERIMENTAL")


def test_upload_validation(client, auth):
    h = auth("clinician")
    pid = new_patient(client, h)
    assert upload(client, h, pid, wav(), consent=False).status_code == 422
    bad = upload(client, h, pid, b"definitely not audio", filename="x.wav")
    assert bad.status_code == 422 and bad.json()["detail"]["recommend_rerecord"]
    assert upload(client, h, pid, wav(), ct="application/pdf").status_code == 415
    assert upload(client, h, pid, b"\0" * (3 * 1024 * 1024)).status_code == 413  # limit 2 MB in tests
    assert upload(client, h, pid, wav(), device="toaster").status_code == 422


def test_role_permissions(client, auth):
    hc, hr, ha = auth("clinician"), auth("researcher"), auth("admin")
    # Researchers have no access to identifiable patient data or audio.
    assert client.get("/api/v1/patients", headers=hr).status_code == 403
    assert client.get("/api/v1/dashboard", headers=hr).status_code == 403
    # Clinicians have no access to research lab or admin.
    assert client.get("/api/v1/research/models", headers=hc).status_code == 403
    assert client.get("/api/v1/admin/users", headers=hc).status_code == 403
    assert client.get("/api/v1/research/models", headers=hr).status_code == 200
    assert client.get("/api/v1/admin/users", headers=ha).status_code == 200
    # Only admins may erase patients.
    pid = new_patient(client, hc)
    assert client.delete(f"/api/v1/patients/{pid}", headers=hc).status_code == 403
    assert client.delete(f"/api/v1/patients/{pid}", headers=ha).status_code == 200


def test_patient_record_isolation_between_organisations(client, auth):
    h1, h2 = auth("clinician"), auth("other_clinician")
    pid = new_patient(client, h1)
    rid = upload(client, h1, pid, wav()).json()["id"]
    assert client.get(f"/api/v1/patients/{pid}", headers=h2).status_code == 404
    assert client.get(f"/api/v1/recordings/{rid}", headers=h2).status_code == 404
    assert client.get(f"/api/v1/recordings/{rid}/audio", headers=h2).status_code == 404
    assert upload(client, h2, pid, wav()).status_code == 404
    assert client.get("/api/v1/patients", headers=h2).json() == []
    assert client.post(f"/api/v1/recordings/{rid}/reviews", headers=h2, json={"status": "reviewed"}).status_code == 404


def test_audio_deletion_destroys_object(client, auth, db):
    h = auth("clinician")
    pid = new_patient(client, h)
    rid = upload(client, h, pid, wav()).json()["id"]
    key = db.get(Patient, pid).recordings[0].storage_key
    assert get_storage().exists(key)
    assert client.delete(f"/api/v1/recordings/{rid}", headers=h).json()["audio_destroyed"] is True
    assert not get_storage().exists(key)
    assert client.get(f"/api/v1/recordings/{rid}/audio", headers=h).status_code == 404
    assert client.get(f"/api/v1/recordings?patient_id={pid}", headers=h).json() == []


def test_patient_erasure_destroys_all_audio(client, auth, db):
    hc, ha = auth("clinician"), auth("admin")
    pid = new_patient(client, hc, external_ref="MRN-1")
    for _ in range(2):
        upload(client, hc, pid, wav())
    keys = [r.storage_key for r in db.get(Patient, pid).recordings]
    assert client.delete(f"/api/v1/patients/{pid}", headers=ha).json()["audio_objects_destroyed"] == 2
    assert not any(get_storage().exists(k) for k in keys)
    assert client.get(f"/api/v1/patients/{pid}", headers=hc).status_code == 404


def test_retention_purge(client, auth, db):
    from datetime import datetime, timedelta, timezone

    h, ha = auth("clinician"), auth("admin")
    pid = new_patient(client, h)
    upload(client, h, pid, wav())
    rec = db.get(Patient, pid).recordings[0]
    rec.retention_until = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    assert client.post("/api/v1/admin/retention/purge", headers=ha).json()["recordings_purged"] == 1
    assert client.put("/api/v1/admin/settings", headers=ha, json={"retention_days": 10}).status_code == 422
    assert client.put("/api/v1/admin/settings", headers=ha, json={"retention_days": 90}).json()["retention_days"] == 90


def test_audit_tamper_detected(client, auth, db):
    h = auth("clinician")
    new_patient(client, h)
    ev = db.query(AuditEvent).filter_by(action="patient.create").one()
    ev.details = {"pseudonym": "edited"}
    db.commit()
    assert client.get("/api/v1/admin/audit/verify", headers=auth("admin")).json()["intact"] is False


def test_search_patients(client, auth):
    h = auth("clinician")
    new_patient(client, h, external_ref="ABC-123")
    new_patient(client, h)
    assert len(client.get("/api/v1/patients?q=abc", headers=h).json()) == 1
    assert len(client.get("/api/v1/patients", headers=h).json()) == 2


def test_demo_data_is_labelled(client, users, db):
    from app.seed import seed

    seed(db)
    r = client.post("/api/v1/auth/login", json={"email": "clinician@demo.cardiolens.local", "password": "demo-password-123"})
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    recs = client.get("/api/v1/recordings", headers=h).json()
    assert recs and all(x["is_demo"] and x["original_filename"].startswith("DEMO-") for x in recs)
    assert all(p["is_synthetic"] for p in client.get("/api/v1/patients", headers=h).json())
    rep = client.get(f"/api/v1/recordings/{recs[0]['id']}/report", headers=h).json()
    assert rep["is_demo"] and any("SYNTHETIC" in s for s in rep["statements"])


def test_research_lab_evaluation_flow(client, auth):
    hr, ha = auth("researcher"), auth("admin")
    ds = client.post("/api/v1/research/datasets", headers=hr, json={
        "name": "Internal set", "license": "internal", "permitted_use": "research", "provenance": "test", "label_definitions": "0/1"}).json()
    m = client.post("/api/v1/research/models", headers=hr, json={
        "name": "m", "version": "1", "intended_use": "x", "categories": [{"id": "a"}], "training_datasets": ["Internal set"]}).json()
    # Researchers cannot self-declare external validation.
    r = client.post("/api/v1/research/models", headers=hr, json={
        "name": "m", "version": "2", "intended_use": "x", "categories": [], "validation_status": "externally_validated", "validation_evidence": "x"})
    assert r.status_code == 403
    assert client.post("/api/v1/research/models", headers=ha, json={
        "name": "m", "version": "3", "intended_use": "x", "categories": [], "validation_status": "externally_validated"}).status_code == 422

    rows = "recording_id,patient_id,label,score,split,quality_pass\n" + "\n".join(
        f"r{i},p{i},{i % 2},{0.7 if i % 2 else 0.3},test,1" for i in range(20))
    files = {"predictions": ("p.csv", rows, "text/csv"), "training_manifest": ("t.csv", "patient_id\nx1\nx2\n", "text/csv")}
    ev = client.post("/api/v1/research/evaluations", headers=hr, data={"model_version_id": m["id"], "dataset_id": ds["id"]}, files=files)
    assert ev.status_code == 201, ev.text
    assert ev.json()["headline"]["sensitivity"] == 1.0
    # Training dataset cannot be used as "external" validation.
    ext = client.post("/api/v1/research/evaluations", headers=hr, data={"model_version_id": m["id"], "dataset_id": ds["id"], "is_external": "true"},
                      files={"predictions": ("p.csv", rows, "text/csv")})
    assert ext.status_code == 422
    leak = client.post("/api/v1/research/evaluations", headers=hr, data={"model_version_id": m["id"], "dataset_id": ds["id"]},
                       files={"predictions": ("p.csv", rows, "text/csv"), "training_manifest": ("t.csv", "patient_id\np3\n", "text/csv")})
    assert leak.status_code == 422 and "leakage" in leak.json()["detail"]
    assert len(client.get("/api/v1/research/evaluations", headers=hr).json()) == 1
