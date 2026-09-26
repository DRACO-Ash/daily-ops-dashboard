**BLUESTAQ LIMITED** | Daily Operations Dashboard | **COMMERCIAL IN CONFIDENCE**

# Bluestaq App Store deployment

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Last updated:** 2026-09-26

> **BLUF**
>
> One container, built from the root `Dockerfile`. FastAPI serves the API on `/api/v1` and the built React app on everything else. Listens on `$PORT` (default 8080), plain HTTP, `GET /` returns 200. Needs the PostgreSQL and File storage add-ons plus three secrets.

## Build the package

```sh
./scripts/package-appstore.sh
```

Produces `dist/daily-ops-dashboard-<version>.zip` from the committed tree. Excluded: `.github/`, `infra/`, the local-dev Dockerfiles under `backend/` and `frontend/`, `scripts/dev.ps1`, and the root `.xlsx`, `.docx` and `README_CLASSIFICATION.txt` files.

## How the container starts

`deploy/entrypoint.sh`:

● Runs `alembic upgrade head`, retrying every 5 seconds (30 attempts, `MIGRATION_ATTEMPTS`) while the Postgres add-on starts. A Postgres advisory lock serialises migrations across replicas.
● Creates or updates an admin user if `ADMIN_USERNAME` and `ADMIN_PASSWORD` are both set. Set them for the first deploy, sign in, then remove them.
● Starts uvicorn on `${PORT:-8080}` as non-root user 10001.

## Upload wizard values

| Field | Value |
|-------|-------|
| App name | `daily-ops-dashboard` (becomes the URL slug; choose once) |
| Display name | Daily Operations Dashboard |
| Short description | Watch-stand picture for SDA analysts: UDL, Mattermost, procedures |
| Category | `MISSION_OPS` |
| App type | `WEB_APP` |
| Version | `0.2.0` |

**Services.** One service, root Dockerfile, port 8080, health check `/`. If the wizard pre-detects `frontend` and `backend` as separate services, collapse to the single root service.

**Resources.** The platform default (128Mi) is too small for this app. Start at 512Mi memory and 500m CPU limits.

**Add-ons.** Enable **PostgreSQL** (required; the app reads `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`) and **File storage** (procedure uploads land in `$STORAGE_MOUNT_PATH/procedures`). Redis and ClamAV are not needed.

## Environment variables

Mark every credential as secret.

| Variable | Required | Notes |
|----------|----------|-------|
| `APP_SECRET_KEY` | Yes, secret | JWT signing key, 32 or more random characters |
| `APP_ENV` | Yes | `production` (disables `/api/docs`) |
| `ANTHROPIC_API_KEY` | For the assistant, secret | |
| `UDL_USERNAME`, `UDL_PASSWORD` | For UDL ingest, secret | |
| `MATTERMOST_URL`, `MATTERMOST_BOT_TOKEN`, `MATTERMOST_TEAM_ID`, `MATTERMOST_CHANNEL_IDS` | For Mattermost ingest, token secret | |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | First deploy only, secret | Remove after first sign-in |
| `BACKGROUND_REFRESH_ENABLED` | No | Default `true` |

Everything else in `.env.example` has a working default. `APP_ALLOWED_ORIGINS` can stay empty because the frontend and API share one origin.

## Known constraints

● **Pipeline template.** Unit coverage is currently around 56%. The python template's SonarQube gate needs 80%, so this package is built to run through the root Dockerfile. If the platform applies the gate anyway, coverage is the gap to close.
● **Replicas.** Keep `replicaCount` at 1. The UDL, maneuver and Mattermost refresh loops run in every replica and would duplicate ingest and AI calls.
● **Frontend dependency.** `react-router-dom` 6 carries a moderate advisory (GHSA-2j2x-hqr9-3h42) that needs a v7 upgrade.
