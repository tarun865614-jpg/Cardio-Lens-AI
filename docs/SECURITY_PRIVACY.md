# Security, privacy and clinical boundaries

## Implemented

| Control | Implementation |
|---|---|
| Consent | Upload refused without `consent_confirmed`; consent version stored per recording. |
| Encryption at rest | Audio encrypted client-side with Fernet (AES-128-CBC + HMAC-SHA256) before storage; on S3 additionally SSE-KMS; random object keys with no patient data; SHA-256 integrity check on read; erasure removes all S3 object versions. |
| Schema integrity | Alembic migrations; production refuses to start on a database not at the latest revision; audit-chain appends serialised by a PostgreSQL advisory lock. |
| Encryption in transit | Deploy behind TLS (reverse proxy / load balancer). The app sets `no-store`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. |
| Authentication | **OIDC mode:** SSO via any OIDC IdP (Authorization Code + PKCE), access tokens verified against IdP JWKS (asymmetric algorithms only, issuer/audience/expiry checked), **MFA enforced** via `amr`, roles from IdP claims with changes audited, password sign-in disabled. **Local mode:** scrypt hashes, short-lived HS256 tokens, account lockout after repeated failures with admin unlock. |
| Authorisation | Role-based (`clinician`, `researcher`, `admin`); researchers have no access to patient records or audio. |
| Tenant isolation | Every query scoped by `org_id`; cross-org access returns 404. |
| Audit | Hash-chained append-only log of logins (incl. failures), views, audio access, uploads, reviews, exports, deletions, settings and user changes; integrity verification endpoint/UI. |
| Deletion | Recording delete destroys the audio object; patient erasure destroys all audio and clears the site reference; audit retained. |
| Retention | Per-organisation retention days; purge endpoint (schedule it daily in production). |
| Data minimisation | Pseudonymous IDs; birth year (not date) and sex optional; no names/addresses. |
| Temp files | Non-WAV transcoding happens in a private temp dir removed immediately. |
| Secrets | Only via environment; production refuses to start with default JWT secret, missing storage key, or demo seeding enabled. |
| Synthetic data | Demo accounts/patients/recordings are flagged and labelled "DEMO · synthetic" everywhere, including reports. |

## Required before real-patient use

* Connect your real IdP tenant and S3 bucket/KMS key (implemented; see `docs/PRODUCTION_SETUP.md`).
* Fetch `CARDIOLENS_STORAGE_KEY` from a secrets manager and define a key-rotation procedure; network-level rate limiting / WAF in front of the API.
* PostgreSQL with encryption at rest, backups, PITR; anchor the audit-chain head externally (e.g. periodic signed export).
* Penetration test and security review; dependency scanning; WAF.
* DPIA / privacy impact assessment; data-processing agreements; jurisdiction-specific obligations (HIPAA, GDPR/UK GDPR, etc.).
* Medical-device regulatory assessment (intended use, classification, QMS, post-market surveillance).

## Incident handling (outline)

1. **Detect** — audit-chain verification failure, anomalous access patterns, failed-login spikes, integrity-check failures on audio reads.
2. **Contain** — deactivate affected accounts (Settings → Access control), rotate `CARDIOLENS_JWT_SECRET` (invalidates all local-mode tokens) or, in SSO mode, revoke sessions at the identity provider; restrict network access.
3. **Assess** — use the audit log to determine which records/audio were accessed, by whom and when.
4. **Notify** — follow organisational and legal breach-notification timelines (e.g. 72 h under GDPR) with the DPO/privacy officer.
5. **Recover & review** — restore from backups if needed, rotate storage keys, document root cause and corrective actions.

## Clinical boundaries (product rules)

* No automatic diagnosis, treatment recommendation or reassurance. The UI never states that a heart is healthy.
* Every analysis carries: "decision support, not a diagnosis", "a low score does not mean the heart is healthy", and urgent-care guidance.
* The New Recording page shows urgent-care guidance when the clinician indicates severe/urgent symptoms.
* Technical recording failures and clinical flags are visually and semantically separate.
* Smartphone microphones are never presented as equivalent to an electronic stethoscope.
