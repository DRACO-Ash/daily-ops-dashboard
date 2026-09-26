# Bluestaq App Store single-container build.
#
# Stage 1 builds the React bundle; stage 2 runs FastAPI, which serves
# both /api/v1 and the built frontend. Listens on $PORT (default 8080),
# plain HTTP. No ENV PORT and no secrets here: all config arrives as
# runtime environment variables (see deploy/APPSTORE.md).

FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    STATIC_DIR=/app/static
WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY deploy/entrypoint.sh ./entrypoint.sh
COPY --from=frontend /build/dist ./static

RUN chmod 0555 ./entrypoint.sh \
    && mkdir -p /data/procedures \
    && chown -R app:app /data

USER 10001
EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
