# Single-container image: builds the frontend and serves it from FastAPI (same origin).
# Used by the Render blueprint (render.yaml); also runs anywhere Docker runs.
FROM node:20-alpine AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=web /src/dist ./static
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser
ENV STATIC_DIR=/app/static ENVIRONMENT=production HOST_TELEMETRY_ENABLED=false \
    DATABASE_URL=sqlite:////app/data/carbon_debt.db PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
