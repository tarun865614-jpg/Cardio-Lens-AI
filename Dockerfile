# Single-container build: FastAPI serves the API and the built SPA.
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /app/frontend/dist /app/frontend/dist
USER app
ENV CARDIOLENS_ENV=production CARDIOLENS_SEED_DEMO_DATA=false CARDIOLENS_SCHEMA_MODE=migrate CARDIOLENS_STORAGE_DIR=/data/recordings
EXPOSE 8000
# Apply database migrations, then serve. (For multi-replica deployments run the
# migration as a one-off release job instead and start replicas with uvicorn only.)
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
