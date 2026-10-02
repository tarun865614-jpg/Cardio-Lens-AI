"""OpenID Connect resource-server support.

The SPA signs in at the identity provider (Authorization Code + PKCE) and sends
the IdP-issued **access token** as a bearer token. This module verifies it
against the IdP's published keys (JWKS) and maps it onto a CardioLens user.

Works with any standards-compliant IdP (Microsoft Entra ID, Okta, Auth0,
Keycloak, Google Workspace via a broker…). The IdP is the source of truth for
identity, MFA and role; CardioLens keeps the user row for org scoping,
deactivation and audit.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import lru_cache

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import Organization, Role, User

ALLOWED_ALGS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384"]  # never HS* for IdP tokens
MFA_AMR = {"mfa", "otp", "hwk", "swk", "sc", "fpt", "face", "iris", "retina", "vbm", "pop"}
ROLE_PRIORITY = [Role.admin.value, Role.clinician.value, Role.researcher.value]

_discovery_cache: dict[str, tuple[float, dict]] = {}


def discovery(issuer: str) -> dict:
    hit = _discovery_cache.get(issuer)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        doc = httpx.get(url, timeout=5.0).raise_for_status().json()
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider discovery failed") from e
    if doc.get("issuer", "").rstrip("/") != issuer.rstrip("/"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider issuer mismatch")
    _discovery_cache[issuer] = (time.time(), doc)
    return doc


@lru_cache(maxsize=4)
def _jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def jwks_client() -> jwt.PyJWKClient:
    s = get_settings()
    return _jwk_client(s.oidc_jwks_url or discovery(s.oidc_issuer)["jwks_uri"])


def _unauthorized(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg)


def verify_access_token(token: str, client: jwt.PyJWKClient | None = None) -> dict:
    s = get_settings()
    try:
        key = (client or jwks_client()).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=ALLOWED_ALGS, audience=s.oidc_audience, issuer=s.oidc_issuer,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=30)
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired — sign in again")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid identity token")
    if s.oidc_require_mfa:
        amr = claims.get("amr") or []
        if isinstance(amr, str):
            amr = [amr]
        if not MFA_AMR & set(amr):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Multi-factor authentication is required for CardioLens")
    return claims


def _claim(claims: dict, path: str):
    cur: object = claims
    for part in path.split("."):  # supports nested claims, e.g. Keycloak 'realm_access.roles'
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def role_from_claims(claims: dict) -> str | None:
    s = get_settings()
    raw = _claim(claims, s.oidc_role_claim)
    values = [raw] if isinstance(raw, str) else list(raw or [])
    mapping = s.role_map()
    mapped = {mapping[v] for v in values if v in mapping}
    for r in ROLE_PRIORITY:
        if r in mapped:
            return r
    return None


def resolve_user(db: Session, claims: dict) -> User:
    """Find (or link / provision) the CardioLens user for verified IdP claims."""
    s = get_settings()
    subject = f"{claims['iss']}|{claims['sub']}"
    role = role_from_claims(claims)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account has no CardioLens role assigned at the identity provider")

    changed = False
    user = db.scalar(select(User).where(User.external_subject == subject))
    email = (claims.get("email") or "").strip().lower()
    if user is None and email and claims.get("email_verified", True) is not False:
        user = db.scalar(select(User).where(func.lower(User.email) == email, User.external_subject.is_(None)))
        if user is not None:
            user.external_subject = subject
            changed = True
            audit.record(db, user, "auth.sso_link", "user", user.id, {"issuer": claims["iss"]})
    if user is None:
        if not (s.oidc_auto_provision and s.oidc_default_org and email):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not provisioned in CardioLens — contact an administrator")
        org = db.scalar(select(Organization).where(Organization.name == s.oidc_default_org))
        if org is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Default organisation for provisioning does not exist")
        user = User(org_id=org.id, email=email, full_name=claims.get("name") or email, role=role,
                    password_hash="!sso-only", external_subject=subject)
        db.add(user)
        db.flush()
        changed = True
        audit.record(db, user, "auth.sso_provision", "user", user.id, {"role": role, "issuer": claims["iss"]})

    if not user.is_active:
        raise _unauthorized("User inactive")
    if user.role != role:
        audit.record(db, user, "user.role_sync", "user", user.id, {"from": user.role, "to": role, "source": "idp"})
        user.role = role
        changed = True
    if changed:
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
    return user


def public_config() -> dict:
    """What the browser needs to start Authorization Code + PKCE. Contains no secrets."""
    s = get_settings()
    if s.auth_mode != "oidc":
        return {"mode": "local"}
    return {"mode": "oidc", "issuer": s.oidc_issuer, "client_id": s.oidc_client_id, "audience": s.oidc_audience,
            "scopes": s.oidc_scopes}
