# CardioLens AI

Research platform for capturing, quality-checking and reviewing heart-sound recordings, with a model-integration layer and
an evaluation lab built for a credible path to clinical validation.

> **Status: research prototype — not a medical device.** No clinical model is bundled. The app runs in clearly labelled
> **research-demo mode** and reports signal-quality and acoustic measurements only. It never fabricates a model result,
> accuracy figure or diagnosis.

## What's in the box

| Area | Working now |
|---|---|
| Capture | Browser mic capture (echo cancellation / noise suppression / AGC disabled) → lossless WAV, live level meter, clipping warning, live waveform; file import (WAV, FLAC, OGG, WebM, MP3, M4A via ffmpeg) |
| Quality intelligence (`sqa-1.0`) | Sample rate, encoding, corruption, duration, clipping, level/silence, dropouts, spectral noise, SNR estimate, motion rumble, cycle regularity (informational); per-window quality; plain-language explanations; re-record prompt; unusable audio never reaches a model |
| Analysis view | Authenticated playback, seekable waveform, spectrogram, band energies, envelope repetition rate (labelled as non-validated) |
| Transparent AI layer | Versioned `inference/v1` contract, HTTP model adapter, strict output validation, timeouts, three result tiers (signal-only / experimental / validated) decided by the model card + intended-use scope, never by the model |
| Clinician workflow | Pseudonymous patients, multiple recordings, quality history, review status, notes, conclusions, follow-up flag, search/filter |
| Reports | HTML & JSON export with separated sections: automated quality · automated model output · clinician conclusions |
| Research lab | Dataset registry with provenance/licence, immutable model registry, evaluation upload with leakage guards; sensitivity/specificity/PPV/NPV (Wilson CIs), ROC + AUC (patient-level bootstrap CI), confusion matrix, calibration (ECE, Brier, slope), subgroup/device/environment breakdown, failed-recording rate; explicit "not evaluated" states |
| Baseline | `python -m app.research.baseline` — transparent features + logistic regression, patient-level split, writes lab-ready predictions |
| Security & privacy | Encrypted audio at rest, RBAC (clinician / researcher / admin), org isolation, consent gate, hash-chained audit log + verification, deletion & erasure, retention purge |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (architecture, schema, API contracts, screens),
[`docs/MODEL_AND_VALIDATION.md`](docs/MODEL_AND_VALIDATION.md) and [`docs/SECURITY_PRIVACY.md`](docs/SECURITY_PRIVACY.md).

## Quick start (development)

Requirements: Python 3.11+, Node 20+, optional `ffmpeg` for non-WAV imports.

```bash
# Backend (http://127.0.0.1:8000, OpenAPI docs at /docs)
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Frontend (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Demo accounts (development only, synthetic data, password `demo-password-123`):
`clinician@demo.cardiolens.local`, `researcher@demo.cardiolens.local`, `admin@demo.cardiolens.local`.

## Tests

```bash
cd backend && python -m pytest                       # 77 tests: quality, inference safety, metrics, API, RBAC, isolation
cd frontend && npm test                              # 9 unit/component tests: WAV encoder, labelling, metric formatting
cd frontend && npm run build && npx playwright test  # 13 end-to-end tests (desktop + mobile, axe accessibility)
```

E2E starts the real backend serving the built SPA with a fresh seeded database. If your Playwright version doesn't match
the installed browser, set `PW_CHROMIUM=/path/to/chromium`.

## Deployment

```bash
cp .env.example .env    # fill in secrets
docker build -t cardiolens .
# or, with PostgreSQL:
POSTGRES_PASSWORD=... CARDIOLENS_JWT_SECRET=... CARDIOLENS_STORAGE_KEY=... docker compose -f deploy/docker-compose.yml up
```

The container serves API + SPA on port 8000. Production mode refuses to start with a default JWT secret, without a storage
key, or with demo seeding enabled. Terminate TLS in front of it, schedule `POST /api/v1/admin/retention/purge` daily, and
review `docs/SECURITY_PRIVACY.md` before handling real data.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `CARDIOLENS_ENV` | `development` | `production` enables startup safety checks |
| `CARDIOLENS_DATABASE_URL` | `sqlite:///./cardiolens.db` | `postgresql+psycopg://…` in production |
| `CARDIOLENS_JWT_SECRET` | dev placeholder | **required** in production (≥32 chars) |
| `CARDIOLENS_JWT_TTL_MINUTES` | `60` | |
| `CARDIOLENS_STORAGE_KEY` | derived (dev only) | **required** in production; Fernet key |
| `CARDIOLENS_STORAGE_DIR` | `./data/recordings` | encrypted audio objects |
| `CARDIOLENS_MAX_UPLOAD_MB` | `20` | |
| `CARDIOLENS_CORS_ORIGINS` | `http://localhost:5173` | comma-separated |
| `CARDIOLENS_SEED_DEMO_DATA` | `true` | must be `false` in production |
| `CARDIOLENS_MODEL_BACKEND` | `none` | `none` · `http` · `local_baseline` |
| `CARDIOLENS_MODEL_SERVICE_URL` | — | for `http` |
| `CARDIOLENS_MODEL_CARD_PATH` | — | card JSON (`http`) or `weights.json` (`local_baseline`) |
| `CARDIOLENS_MODEL_SERVICE_TIMEOUT_S` | `10` | |
| `VITE_API_BASE` (build) | `/api/v1` | frontend API base |
| `VITE_SHOW_DEMO_ACCOUNTS` (build) | `false` | show demo login shortcuts in a production build |

## Needs data, weights, integrations or validation

| Item | Why it's not done |
|---|---|
| A screening model with real performance numbers | Requires licensed, labelled heart-sound datasets downloaded and verified, model training and held-out evaluation. Nothing is claimed until measured. |
| Any accuracy target (e.g. "94%") | Must be defined as sensitivity/specificity with CIs on a stated task, population and device, then demonstrated on external data — see `docs/MODEL_AND_VALIDATION.md`. |
| `validated` result tier in practice | Requires independent clinical validation evidence registered by an admin. |
| Calibrated probabilities | Requires calibration assessment on external data. |
| Tuned quality thresholds | Need human-labelled quality data and per-device false-rejection analysis. |
| Smartphone-microphone suitability | Requires device-specific validation; current UI states the limitation. |
| OIDC/MFA, KMS, cloud object storage, Alembic migrations, EHR/FHIR | Integration work for production. |
| Regulatory clearance, DPIA, clinical governance | Required before any patient-facing or clinical use. |
