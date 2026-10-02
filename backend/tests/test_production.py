"""Production hardening: database migrations, S3 storage, OIDC/MFA sign-in, login lockout, config guards."""

from __future__ import annotations

import time
from types import SimpleNamespace

import boto3
import jwt
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws
from sqlalchemy import create_engine, inspect

from app import oidc
from app.config import Settings, get_settings
from app.database import Base, alembic_config, init_db, schema_status
from app.models import AuditEvent, User
from app.storage import S3EncryptedStorage, StorageError, set_storage

from .conftest import new_patient, upload, wav

# --------------------------------------------------------------------------- migrations


def _migrate(engine, target="head", down=False):
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        (command.downgrade if down else command.upgrade)(cfg, target)


def test_migrations_build_exactly_the_model_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    _migrate(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"models and migrations have drifted: {diff}"
    assert schema_status(engine)[0] == schema_status(engine)[1]


def test_migrations_downgrade_cleanly(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    _migrate(engine)
    _migrate(engine, "base", down=True)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}


def test_migrate_mode_refuses_unmigrated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "schema_mode", "migrate")
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        init_db(engine)
    _migrate(engine)
    init_db(engine)  # now at head: no error


# --------------------------------------------------------------------------- S3 storage


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="cl-test")
        client.put_bucket_versioning(Bucket="cl-test", VersioningConfiguration={"Status": "Enabled"})
        kms = boto3.client("kms", region_name="us-east-1").create_key()["KeyMetadata"]["KeyId"]
        yield SimpleNamespace(client=client, kms=kms)


def test_s3_roundtrip_is_double_encrypted(s3):
    st = S3EncryptedStorage("cl-test", "rec/", None, "secret", kms_key_id=s3.kms, client=s3.client)
    data = wav()
    key = st.put(data)
    assert st.get(key) == data and st.exists(key)
    obj = s3.client.get_object(Bucket="cl-test", Key=f"rec/{key[:2]}/{key}")
    assert obj["ServerSideEncryption"] == "aws:kms"
    stored = obj["Body"].read()
    assert not stored.startswith(b"RIFF") and b"WAVE" not in stored  # client-side ciphertext


def test_s3_delete_removes_all_versions(s3):
    st = S3EncryptedStorage("cl-test", "rec/", None, "secret", client=s3.client)
    key = st.put(b"a")
    name = f"rec/{key[:2]}/{key}"
    s3.client.put_object(Bucket="cl-test", Key=name, Body=b"older-version")  # simulate a second version
    assert st.delete(key) is True
    assert not st.exists(key)
    left = s3.client.list_object_versions(Bucket="cl-test", Prefix=name)
    assert not left.get("Versions")
    assert st.delete(key) is False


def test_s3_errors_and_key_validation(s3):
    st = S3EncryptedStorage("cl-test", "rec/", None, "secret", client=s3.client)
    with pytest.raises(StorageError):
        st.get("ab" * 24)
    with pytest.raises(StorageError):
        st.get("../../etc/passwd")
    other = S3EncryptedStorage("cl-test", "rec/", None, "different-secret", client=s3.client)
    key = st.put(b"x")
    with pytest.raises(StorageError, match="integrity"):
        other.get(key)  # wrong key can't decrypt


def test_full_upload_and_erasure_on_s3(s3, client, auth):
    st = S3EncryptedStorage("cl-test", "rec/", None, "secret", client=s3.client)
    set_storage(st)
    try:
        h = auth("clinician")
        pid = new_patient(client, h)
        data = wav()
        rid = upload(client, h, pid, data).json()["id"]
        assert client.get(f"/api/v1/recordings/{rid}/audio", headers=h).content == data
        assert client.delete(f"/api/v1/recordings/{rid}", headers=h).json()["audio_destroyed"] is True
        assert s3.client.list_objects_v2(Bucket="cl-test").get("KeyCount", 0) == 0
    finally:
        set_storage(None)


# --------------------------------------------------------------------------- OIDC / MFA

ISS = "https://idp.example.org/"
AUD = "api://cardiolens"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


@pytest.fixture
def sso(monkeypatch, users):
    s = get_settings()
    for k, v in dict(auth_mode="oidc", oidc_issuer=ISS, oidc_audience=AUD, oidc_client_id="spa-client",
                     oidc_role_claim="roles", oidc_require_mfa=True, oidc_auto_provision=False, oidc_default_org=None).items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(oidc, "jwks_client", lambda: FakeJWKS())
    return s


def token(sub="u1", email="clinician@test.local", roles=("clinician",), amr=("pwd", "mfa"), aud=AUD, iss=ISS, exp_in=300, key=KEY, alg="RS256", **extra):
    now = int(time.time())
    claims = {"iss": iss, "sub": sub, "aud": aud, "iat": now, "exp": now + exp_in, "email": email, "roles": list(roles), "amr": list(amr), **extra}
    return {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm=alg)}


def test_sso_links_existing_user_by_email_and_audits(client, sso, db):
    r = client.get("/api/v1/auth/me", headers=token())
    assert r.status_code == 200 and r.json()["email"] == "clinician@test.local" and r.json()["sso_linked"]
    assert db.query(AuditEvent).filter_by(action="auth.sso_link").count() == 1
    # Subsequent requests resolve by subject, even if the email claim changes.
    assert client.get("/api/v1/auth/me", headers=token(email="renamed@test.local")).json()["email"] == "clinician@test.local"
    assert client.get("/api/v1/patients", headers=token()).status_code == 200


def test_sso_requires_mfa(client, sso):
    r = client.get("/api/v1/auth/me", headers=token(amr=("pwd",)))
    assert r.status_code == 403 and "Multi-factor" in r.json()["detail"]


@pytest.mark.parametrize("bad", [dict(aud="api://other"), dict(iss="https://evil.example.org/"), dict(exp_in=-120)])
def test_sso_rejects_wrong_audience_issuer_or_expired(client, sso, bad):
    assert client.get("/api/v1/auth/me", headers=token(**bad)).status_code == 401


def test_sso_rejects_token_signed_with_other_key_or_hmac(client, sso):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert client.get("/api/v1/auth/me", headers=token(key=other)).status_code == 401
    # Algorithm-confusion attempt: HS256 token signed with the app's local secret.
    assert client.get("/api/v1/auth/me", headers=token(key=get_settings().jwt_secret, alg="HS256")).status_code == 401


def test_sso_role_comes_from_idp_and_changes_are_audited(client, sso, db):
    client.get("/api/v1/auth/me", headers=token())
    r = client.get("/api/v1/auth/me", headers=token(roles=("researcher",)))
    assert r.json()["role"] == "researcher"
    assert client.get("/api/v1/patients", headers=token(roles=("researcher",))).status_code == 403
    assert db.query(AuditEvent).filter_by(action="user.role_sync").count() == 1


def test_sso_without_role_or_provisioning_is_denied(client, sso):
    assert client.get("/api/v1/auth/me", headers=token(roles=())).status_code == 403
    r = client.get("/api/v1/auth/me", headers=token(sub="new", email="stranger@test.local"))
    assert r.status_code == 403 and "not provisioned" in r.json()["detail"]


def test_sso_auto_provisioning(client, sso, monkeypatch, db):
    monkeypatch.setattr(sso, "oidc_auto_provision", True)
    monkeypatch.setattr(sso, "oidc_default_org", "Org A")
    r = client.get("/api/v1/auth/me", headers=token(sub="n2", email="new.doc@test.local", name="New Doc"))
    assert r.status_code == 200 and r.json()["role"] == "clinician" and r.json()["full_name"] == "New Doc"
    u = db.query(User).filter_by(email="new.doc@test.local").one()
    assert u.password_hash.startswith("!")  # cannot be used for password login


def test_sso_deactivated_user_blocked(client, sso, db):
    db.query(User).filter_by(email="clinician@test.local").update({"is_active": False})
    db.commit()
    assert client.get("/api/v1/auth/me", headers=token()).status_code == 401


def test_sso_nested_role_claim(client, sso, monkeypatch):
    monkeypatch.setattr(sso, "oidc_role_claim", "realm_access.roles")
    monkeypatch.setattr(sso, "oidc_role_map", "cl-admins:admin,cl-clinicians:clinician")
    r = client.get("/api/v1/auth/me", headers=token(roles=(), realm_access={"roles": ["cl-clinicians", "offline_access"]}))
    assert r.status_code == 200 and r.json()["role"] == "clinician"


def test_sso_mode_disables_password_login_and_exposes_public_config(client, sso):
    assert client.post("/api/v1/auth/login", json={"email": "clinician@test.local", "password": "x"}).status_code == 404
    cfg = client.get("/api/v1/auth/config").json()
    assert cfg == {"mode": "oidc", "issuer": ISS, "client_id": "spa-client", "audience": AUD, "scopes": "openid profile email"}


def test_sso_admin_can_preprovision_without_password(client, sso):
    h = token(sub="adm", email="admin@test.local", roles=("admin",))
    r = client.post("/api/v1/admin/users", headers=h, json={"email": "doc2@test.local", "full_name": "Doc Two", "role": "clinician"})
    assert r.status_code == 201


# --------------------------------------------------------------------------- local login lockout


def test_login_lockout_and_admin_unlock(client, users, auth):
    from .conftest import PW

    bad = {"email": "clinician@test.local", "password": "wrong-password"}
    for _ in range(get_settings().login_max_failures):
        assert client.post("/api/v1/auth/login", json=bad).status_code == 401
    good = {"email": "clinician@test.local", "password": PW}
    assert client.post("/api/v1/auth/login", json=good).status_code == 429  # locked even with the right password
    ha = auth("admin")
    uid = users["clinician"].id
    assert client.patch(f"/api/v1/admin/users/{uid}", headers=ha, json={"unlock": True}).status_code == 200
    assert client.post("/api/v1/auth/login", json=good).status_code == 200


def test_local_user_creation_still_requires_password(client, auth):
    r = client.post("/api/v1/admin/users", headers=auth("admin"), json={"email": "x@test.local", "full_name": "X", "role": "clinician"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- configuration guards


@pytest.mark.parametrize("kw,msg", [
    (dict(env="production", jwt_secret="x" * 40, storage_key="k", seed_demo_data=False, schema_mode="create"), "SCHEMA_MODE"),
    (dict(auth_mode="oidc"), "OIDC mode requires"),
    (dict(storage_backend="s3"), "S3_BUCKET"),
    (dict(auth_mode="ldap"), "AUTH_MODE"),
])
def test_runtime_config_guards(kw, msg):
    with pytest.raises(RuntimeError, match=msg):
        Settings(**kw).validate_for_runtime()


def test_production_config_accepted_when_complete():
    Settings(env="production", jwt_secret="x" * 40, storage_key="k", seed_demo_data=False, schema_mode="migrate",
             auth_mode="oidc", oidc_issuer=ISS, oidc_audience=AUD, oidc_client_id="c", storage_backend="s3", s3_bucket="b").validate_for_runtime()
