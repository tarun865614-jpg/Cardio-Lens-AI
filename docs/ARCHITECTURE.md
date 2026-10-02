# CardioLens AI — Architecture

## 1. System overview

```
 Browser (React + TS + Tailwind)                     FastAPI service (Python)                         External (optional)
 ┌──────────────────────────────┐   HTTPS/JSON   ┌──────────────────────────────────────────┐
 │ Dashboard · New Recording    │ ─────────────► │ /api/v1  auth · patients · recordings    │
 │ Audio Analysis · Patients    │  Bearer token  │          reviews · reports · research    │
 │ Research Lab · Reports       │                │          admin · system                  │
 │ Settings                     │                │                                          │
 │ Web Audio capture → WAV      │                │  Analysis pipeline (inference/service.py)│     ┌───────────────────┐
 └──────────────────────────────┘                │  decode → validate → quality gate →      │ ──► │ Model service     │
                                                 │  preprocess → adapter → contract check → │     │ (PyTorch/Triton…) │
                                                 │  tier labelling                          │ ◄── │ inference/v1      │
                                                 │                                          │     └───────────────────┘
                                                 │  Encrypted object storage (Fernet)       │
                                                 │  PostgreSQL / SQLite (SQLAlchemy 2)      │
                                                 │  Hash-chained audit log                  │
                                                 └──────────────────────────────────────────┘
```

The model never runs in the browser and the UI never talks to a model directly. Models are replaceable by changing
configuration (`CARDIOLENS_MODEL_BACKEND`, `CARDIOLENS_MODEL_SERVICE_URL`, `CARDIOLENS_MODEL_CARD_PATH`).

## 2. Processing pipeline

| Stage | Module | Notes |
|---|---|---|
| Input | `audio/decode.py` | WAV native (8/16/24/32-bit int, float). FLAC/OGG/WebM/MP3/M4A via ffmpeg in a temp dir that is deleted immediately. Lossy formats flagged. |
| Validation | `audio/decode.py`, `routers/recordings.py` | Size limit, content type, magic-byte sniffing, consent required, enum-checked metadata. |
| Quality assessment | `audio/quality.py` (`sqa-1.0`) | Sample rate, encoding, integrity (NaN/Inf), duration, clipping, level/silence, dropouts, spectral noise, SNR estimate, low-frequency rumble, cycle regularity (informational only). |
| Preprocessing | `audio/preprocess.py` | DC removal, polyphase resampling to 2 kHz for analysis. Model-specific filtering is declared in the model card and done by the adapter. |
| Segmentation | `quality.window_quality` | 5 s windows, 2.5 s hop, per-window SNR and regularity. |
| Inference | `inference/adapters.py` | `HttpModelAdapter` (external service) or `LocalBaselineAdapter` (research baseline). Thread-pool timeout. |
| Calibration / labelling | `inference/base.py`, `inference/service.py` | Strict contract validation; tier = `signal_only` / `experimental` / `validated`. |
| Review | `routers/recordings.py` | Clinician reviews, flags, conclusions; audit trail. |

### Safety invariants (enforced in code and tests)

1. Recordings failing the quality gate are never sent to a model; the user is asked to re-record.
2. No model configured → research-demo mode: signal measurements only, nothing resembling a diagnosis.
3. Any inference error, timeout, malformed or out-of-contract response → `service_error` with **no** result. There is no fallback output.
4. `validated` tier requires a model card with `externally_validated` status **and** cited evidence **and** a recording within the card's declared devices/sites **and** a recording with no quality warnings. Otherwise `experimental`.
5. Uncalibrated scores are labelled "not a probability of disease"; percentages are never shown for model scores.
6. A local weights file cannot self-certify — `LocalBaselineAdapter` forces `research_only`.
7. Only admins can register an `externally_validated` model, and evidence is mandatory.

## 3. Database schema

| Table | Key columns | Purpose |
|---|---|---|
| `organizations` | id, name, retention_days | Tenant boundary for isolation and retention policy. |
| `users` | id, org_id, email, role (`clinician`/`researcher`/`admin`), password_hash (scrypt), is_active | Accounts / RBAC. |
| `patients` | id, org_id, pseudonym (`CL-XXXXXX`), external_ref?, birth_year?, sex?, is_synthetic, deleted_at | Minimal data; generated identifier. |
| `recordings` | id, org_id, patient_id, storage_key, sha256, size, sample_rate, channels, duration_s, device_type, auscultation_site, environment, consent_confirmed, consent_version, is_demo, quality_status, review_status, retention_until, deleted_at | Audio metadata; audio itself is in encrypted storage. |
| `analyses` | id, recording_id, pipeline_version, quality_report (JSON), signal_summary (JSON), model_status, result_tier, model_name, model_version, model_output (JSON), error | Every analysis run is kept (reproducibility). |
| `reviews` | id, recording_id, reviewer_id, status, note, clinician_conclusion, flagged_for_followup | Clinician-in-the-loop. |
| `audit_events` | id, ts, org_id, actor_id, action, entity_type, entity_id, details, prev_hash, hash | Append-only SHA-256 hash chain. |
| `datasets` | name, source_url, license, permitted_use, provenance, label_definitions, devices, population, limitations | Dataset registry with provenance. |
| `model_versions` | name+version (unique, immutable), intended_use, categories, validation_status, validation_evidence, training_datasets, weights_sha256 | Model registry. |
| `evaluation_runs` | model_version_id, dataset_id, split_name, is_external, threshold, metrics (JSON), warnings | Evaluation lab results. |

Tables are created with `create_all` for the prototype. Add Alembic migrations before the first production deployment.

## 4. API contracts (v1)

All endpoints are under `/api/v1`, JSON unless noted, bearer-token authenticated except `/auth/login` and `/health`.
Other organisations' resources return **404** (not 403) so existence is not revealed.

| Method & path | Roles | Description |
|---|---|---|
| `POST /auth/login` | — | `{email,password}` → `{access_token, user}` (failures audited) |
| `GET /auth/me` | any | Current user |
| `GET /system/status` | any | Analysis mode, pipeline & contract versions, ffmpeg availability |
| `GET /dashboard` | clinician, admin | Counts, recent, pending, flagged, quality issues, system |
| `GET/POST /patients` | clinician, admin | List (`q`, `has_open_reviews`) / create |
| `GET /patients/{id}` · `DELETE` | clinical · admin | Detail with recordings · erase (destroys all audio) |
| `POST /patients/{id}/recordings` | clinician, admin | multipart: `file`, `consent_confirmed`, `device_type`, `auscultation_site`, `environment`, `recorded_at` → recording + analysis |
| `GET /recordings` | clinician, admin | Filters: `review_status`, `quality_status`, `patient_id` |
| `GET /recordings/{id}` | clinician, admin | Detail incl. analyses and reviews |
| `GET /recordings/{id}/audio` | clinician, admin | Original bytes (integrity-checked, `no-store`, audited) |
| `POST /recordings/{id}/reanalyze` | clinician, admin | New analysis row with current pipeline/model |
| `DELETE /recordings/{id}` | clinician, admin | Destroys audio object; metadata/audit retained |
| `POST /recordings/{id}/reviews` | clinician, admin | `{status, note, clinician_conclusion, flagged_for_followup}` |
| `GET /recordings/{id}/report?format=json\|html` | clinician, admin | Report with separated automated / clinician sections |
| `GET/POST /research/datasets` | researcher, admin | Dataset registry |
| `GET/POST /research/models` | researcher, admin | Model registry (`externally_validated` admin-only + evidence) |
| `GET/POST /research/evaluations`, `GET /research/evaluations/{id}` | researcher, admin | multipart: `predictions` CSV, optional `training_manifest` CSV, `threshold`, `is_external` |
| `GET/POST/PATCH /admin/users` | admin | User management |
| `GET/PUT /admin/settings` | admin | Retention days (30–3650) |
| `POST /admin/retention/purge` | admin | Destroy audio past retention |
| `GET /admin/audit`, `GET /admin/audit/verify` | admin | Audit log and hash-chain verification |

### Model service contract `inference/v1`

Request — `POST {MODEL_SERVICE_URL}/v1/predict`
```json
{"contract": "inference/v1", "model": {"name": "...", "version": "..."}, "sample_rate": 2000,
 "audio_wav_b64": "<float32 mono WAV>", "metadata": {"device_type": "...", "auscultation_site": "..."}}
```
Response
```json
{"model": {"name": "...", "version": "<must equal card version>"},
 "abstained": false,
 "scores": [{"category": "<id from card>", "score": 0.0}],
 "segments": [{"start_s": 0.0, "end_s": 5.0}]}
```
Every declared category must be present exactly once, scores ∈ [0,1], mutually exclusive categories must sum to 1 (±0.02).
Anything else is rejected and recorded as `service_error`. See `docs/model_card.example.json` for the card format.

### Evaluation upload format

`recording_id, patient_id, label (0/1), score ([0,1], blank if quality failed), split (test|holdout|external), quality_pass (0/1)`
plus optional subgroup columns (`device`, `environment`, `site`, `age_group`, `sex`, …). `python -m app.research.baseline` writes this format.

## 5. Screen structure

| Screen | Route | Roles | Contents |
|---|---|---|---|
| Login | `/login` | — | Sign-in; dev-only demo account shortcuts |
| Dashboard | `/` | clinician, admin | KPI tiles, pending reviews, flagged cases, technical quality issues, system status |
| New Recording | `/record` | clinician, admin | Patient select/create, device/site/environment, urgent-symptom guidance, mic capture with live level/clipping/waveform, file import, consent, upload |
| Audio Analysis | `/recordings/:id` | clinician, admin | Playback, waveform with seek and model segments, spectrogram, measurements, per-window quality, quality checklist, AI panel (tiered), review form + history, export, re-run, delete |
| Patient Records | `/patients`, `/patients/:id` | clinician, admin | Search/filter, create, recordings, quality history, erase (admin) |
| Research Lab | `/research`, `/research/evaluations/:id` | researcher, admin | Evaluations (upload, list, detail with CIs, confusion matrix, ROC, calibration, subgroups/devices), datasets, model registry |
| Reports | `/reports` | clinician, admin | Filterable list, HTML/JSON export |
| Settings | `/settings` | all (admin sections gated) | Privacy notice, integrations/system, users & roles, retention, audit log + integrity check |

Visual language: deep navy / white / muted teal. **Technical recording issues** use an amber "issue" tone with a wrench icon;
**clinical follow-up flags** use a distinct violet with a flag icon; **experimental AI** uses a yellow "experimental" tone.
No alarm-red is used for findings.
