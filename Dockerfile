# Single-container build: React frontend served by FastAPI on one port.
# docker build -t pds4-viewer . && docker run -p 8000:8000 pds4-viewer
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY backend/ /app/backend/
RUN pip install --no-cache-dir --only-binary :all: "/app/backend[s3]"
COPY --from=frontend /src/frontend/dist /app/static
COPY test_data/ /data/
ENV PDS_STATIC_DIR=/app/static \
    PDS_LOCAL_ROOT=/data \
    PDS_CACHE_DIR=/var/cache/pds4_viewer
# Run as an unprivileged user; it only needs to write to the cache dir.
RUN useradd --system --uid 10001 --no-create-home viewer \
    && mkdir -p /var/cache/pds4_viewer \
    && chown viewer /var/cache/pds4_viewer
USER viewer
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
