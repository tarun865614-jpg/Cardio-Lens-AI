# Production setup: SSO with MFA, cloud storage, migrations

This is the runbook for the three production building blocks. Each one is switched on by environment variables only — no code changes.

## 1. Single sign-on with MFA (OIDC)

CardioLens is an OIDC **resource server**. The browser signs in at your identity provider (IdP) using Authorization Code + PKCE (a public client, with no secret in the browser). It then sends the IdP's access token to the API. The API checks the token's signature against the IdP's JWKS, its issuer, audience and expiry, **MFA** (via the `amr` claim) and the **role** claim.

### IdP side (one-time)
1. Register a **single-page application** client:
   - Redirect URI: `https://<your-host>/auth/callback`
   - Post-logout URI: `https://<your-host>/login`
   - Grant type: authorization code with PKCE; no client secret.
2. Register (or reuse) an **API / resource** whose identifier becomes `CARDIOLENS_OIDC_AUDIENCE`, and make sure access tokens are JWTs issued for that audience.
3. Enforce **MFA** with a conditional-access or sign-on policy, and confirm the access token carries `amr` (e.g. `mfa`, `otp`, `hwk`).
4. Emit a **role/group claim** and map its values with `CARDIOLENS_OIDC_ROLE_MAP` (format `idp-value:role`; roles are `clinician`, `researcher`, `admin`).

| IdP | Issuer example | Role claim | Notes |
|---|---|---|---|
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant>/v2.0` | `roles` (app roles) | Set scopes to `openid profile email api://<app-id>/access`. Enable `amr` in token configuration. |
| Okta | `https://<org>.okta.com/oauth2/<server-id>` | `groups` | Add a groups claim to the access token. |
| Auth0 | `https://<tenant>.auth0.com/` | custom namespaced claim, e.g. `https://cardiolens/roles` | The `audience` parameter is sent automatically. |
| Keycloak | `https://<host>/realms/<realm>` | `realm_access.roles` | Nested claim paths are supported. |

### CardioLens side
```
CARDIOLENS_AUTH_MODE=oidc
CARDIOLENS_OIDC_ISSUER=...
CARDIOLENS_OIDC_AUDIENCE=...
CARDIOLENS_OIDC_CLIENT_ID=...
CARDIOLENS_OIDC_ROLE_CLAIM=roles
CARDIOLENS_OIDC_ROLE_MAP=CL.Clinician:clinician,CL.Researcher:researcher,CL.Admin:admin
CARDIOLENS_OIDC_REQUIRE_MFA=true
```

User onboarding:
- Admins pre-create users by email under **Settings → Access control**. On first SSO sign-in the account is linked to the IdP subject, and the link is audited.
- Alternatively, set `CARDIOLENS_OIDC_AUTO_PROVISION=true` and `CARDIOLENS_OIDC_DEFAULT_ORG=<org name>`.

Ongoing rules:
- Roles follow the IdP on every request, and any change is audited.
- Deactivating a user in CardioLens blocks them even if the IdP still allows sign-in.
- In OIDC mode, password sign-in is disabled.

**Local mode** (no IdP) remains available for pilots. It locks an account after `CARDIOLENS_LOGIN_MAX_FAILURES` failed attempts for `CARDIOLENS_LOGIN_LOCKOUT_MINUTES`; admins can unlock it from Settings.

## 2. Cloud object storage (S3 + KMS)

Audio is always encrypted in the app (Fernet, using `CARDIOLENS_STORAGE_KEY`) before upload. S3 adds a second, independent layer through SSE-KMS.

```
CARDIOLENS_STORAGE_BACKEND=s3
CARDIOLENS_S3_BUCKET=cardiolens-recordings-prod
CARDIOLENS_S3_REGION=eu-west-2
CARDIOLENS_S3_KMS_KEY_ID=arn:aws:kms:...:key/...
```

Bucket checklist:
- Block all public access.
- Deny non-TLS requests (`aws:SecureTransport`).
- Default encryption: SSE-KMS.
- Turn versioning on. Deletion and erasure remove every version of an object.
- Give the app role only `s3:PutObject`, `GetObject`, `DeleteObject`, `DeleteObjectVersion`, `ListBucketVersions`, `HeadObject` on the prefix, plus `kms:Encrypt`/`Decrypt`/`GenerateDataKey` on the key.

S3-compatible stores such as MinIO work via `CARDIOLENS_S3_ENDPOINT_URL`.

Keep `CARDIOLENS_STORAGE_KEY` in a secrets manager. Losing it makes all audio unrecoverable. Destroying it deliberately is how you crypto-erase everything.

## 3. Database migrations (Alembic)

```
cd backend
alembic upgrade head                                  # apply migrations
alembic revision --autogenerate -m "describe change"  # after changing app/models.py
```

- Production requires `CARDIOLENS_SCHEMA_MODE=migrate`. In that mode the app **refuses to start** unless the database is at the latest revision. The Docker image runs `alembic upgrade head` before starting.
- With multiple replicas, run the migration as a one-off release step instead.
- A test (`test_migrations_build_exactly_the_model_schema`) fails if the models and migrations ever drift apart.
- Audit-log appends are serialised with a PostgreSQL advisory lock, so the hash chain stays intact with many workers.
