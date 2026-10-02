# Security, privacy and clinical boundaries

## Implemented

| Control | Implementation |
|---|---|
| Consent | Upload refused without `consent_confirmed`; consent version stored per recording. |
| Encryption at rest | Audio encrypted with Fernet (AES-128-CBC + HMAC-SHA256); random object keys with no patient data; SHA-256 integrity check on read. |
| Encryption in transit | Deploy behind TLS (reverse proxy / load balancer). The app sets `no-store`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. |
| Authentication | scrypt password hashes; HS256 bearer tokens with expiry. Swap for an OIDC provider in production. |
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

* Managed identity provider with MFA; short token TTL + refresh; account lockout / rate limiting on login.
* Managed KMS for the storage key (envelope encryption, rotation); S3/GCS private bucket with SSE-KMS and versioning-aware deletion.
* PostgreSQL with encryption at rest, backups, PITR; Alembic migrations; audit-chain writes serialised (advisory lock) and the chain head anchored externally.
* Penetration test and security review; dependency scanning; WAF.
* DPIA / privacy impact assessment; data-processing agreements; jurisdiction-specific obligations (HIPAA, GDPR/UK GDPR, etc.).
* Medical-device regulatory assessment (intended use, classification, QMS, post-market surveillance).

## Incident handling (outline)

1. **Detect** — audit-chain verification failure, anomalous access patterns, failed-login spikes, integrity-check failures on audio reads.
2. **Contain** — deactivate affected accounts (Settings → Access control), rotate `CARDIOLENS_JWT_SECRET` (invalidates all tokens), restrict network access.
3. **Assess** — use the audit log to determine which records/audio were accessed, by whom and when.
4. **Notify** — follow organisational and legal breach-notification timelines (e.g. 72 h under GDPR) with the DPO/privacy officer.
5. **Recover & review** — restore from backups if needed, rotate storage keys, document root cause and corrective actions.

## Clinical boundaries (product rules)

* No automatic diagnosis, treatment recommendation or reassurance. The UI never states that a heart is healthy.
* Every analysis carries: "decision support, not a diagnosis", "a low score does not mean the heart is healthy", and urgent-care guidance.
* The New Recording page shows urgent-care guidance when the clinician indicates severe/urgent symptoms.
* Technical recording failures and clinical flags are visually and semantically separate.
* Smartphone microphones are never presented as equivalent to an electronic stethoscope.
