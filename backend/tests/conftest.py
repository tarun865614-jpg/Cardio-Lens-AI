import os
import tempfile

# Configure BEFORE the app is imported (engine/settings are created at import).
_TMP = tempfile.mkdtemp(prefix="cl-test-")
os.environ.update({
    "CARDIOLENS_ENV": "test",
    "CARDIOLENS_DATABASE_URL": "sqlite://",
    "CARDIOLENS_STORAGE_DIR": os.path.join(_TMP, "rec"),
    "CARDIOLENS_SEED_DEMO_DATA": "false",
    "CARDIOLENS_MODEL_BACKEND": "none",
    "CARDIOLENS_MAX_UPLOAD_MB": "2",
    "CARDIOLENS_MODEL_SERVICE_TIMEOUT_S": "0.5",
})

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.audio.synthetic import synth_pcg, to_wav_bytes  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.inference import service  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    service.set_adapter(None)
    yield
    service.set_adapter(None)


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def users(db):
    org1, org2 = Organization(name="Org A"), Organization(name="Org B")
    db.add_all([org1, org2])
    db.flush()
    out = {}
    for key, org, role in [("clinician", org1, "clinician"), ("researcher", org1, "researcher"), ("admin", org1, "admin"),
                           ("other_clinician", org2, "clinician")]:
        u = User(org_id=org.id, email=f"{key}@test.local", full_name=key.title(), role=role, password_hash=hash_password(PW))
        db.add(u)
        out[key] = u
    db.commit()
    return out


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client, who: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": f"{who}@test.local", "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture
def auth(client, users):
    return lambda who: login(client, who)


def wav(kind: str = "clean", sr: int = 4000) -> bytes:
    rng = np.random.default_rng(0)
    if kind == "clean":
        return to_wav_bytes(synth_pcg(sr=sr, duration_s=15), sr)
    if kind == "silence":
        return to_wav_bytes(np.zeros(sr * 15), sr)
    if kind == "clipped":
        return to_wav_bytes(np.clip(synth_pcg(sr=sr, amplitude=3.0), -1, 1), sr)
    if kind == "noise":
        return to_wav_bytes(rng.normal(0, 0.1, sr * 15), sr)
    if kind == "short":
        return to_wav_bytes(synth_pcg(sr=sr, duration_s=3), sr)
    raise ValueError(kind)


def upload(client, headers, patient_id, data: bytes, *, filename="r.wav", ct="audio/wav", consent=True, device="electronic_stethoscope", site="mitral"):
    return client.post(
        f"/api/v1/patients/{patient_id}/recordings",
        headers=headers,
        files={"file": (filename, data, ct)},
        data={"consent_confirmed": str(consent).lower(), "device_type": device, "auscultation_site": site, "environment": "clinic_quiet"},
    )


def new_patient(client, headers, **kw) -> int:
    r = client.post("/api/v1/patients", headers=headers, json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]
