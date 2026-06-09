**BLUESTAQ LIMITED** | Daily Operations Dashboard | **COMMERCIAL IN CONFIDENCE**

# Daily Operations Dashboard

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28
**Status:** Phase 1, active development

> **BLUF**
>
> Operational intelligence tool for space surveillance analysts. Aggregates Unified Data Library (UDL) records, Mattermost activity, ClickUp exports, procedure documents, and analyst inputs into one watch-stand surface for Space Domain Awareness (SDA) operations. Sovereign UK deployment, with a path to allied multi-tenant in Phase 2.

**SECTION 01**

## Why this exists

Analysts on watch spend time stitching together views across UDL, Mattermost, ClickUp, and bespoke spreadsheets. The Daily Operations Dashboard puts the live operational picture in one place, with audit-grade history for every action and a path to AI-assisted triage once Phase 2 lands.

**SECTION 02**

## Quick start

One file does everything:

```powershell
.\scripts\dev.ps1
```

That script (idempotent, safe to re-run on every check-out):

● Creates `.env` from `.env.example` with a fresh `APP_SECRET_KEY` if missing.
● Generates a self-signed TLS certificate via docker if one is not already in `infra/certs/`.
● Brings up the full stack (`db`, `backend`, `frontend`, `nginx`).
● Waits for the database to be ready.
● Applies any pending alembic migrations.
● Bootstraps the first admin user if `app_user` is empty (prompts, or reads `$env:ADMIN_USERNAME` / `$env:ADMIN_PASSWORD`).
● Tails the backend logs (use `-NoLogs` to skip).

Other useful invocations:

```powershell
.\scripts\dev.ps1 -Down       # Stop the stack, keep the database volume.
.\scripts\dev.ps1 -Restart    # Stop, start again without rebuilding.
.\scripts\dev.ps1 -Reset      # Stop and DROP the database volume.
```

When the script settles, open `https://localhost` and accept the self-signed certificate.

Full developer setup, including running the backend or frontend outside docker for hot reload, is in [docs/developer/setup.md](docs/developer/setup.md).

**SECTION 03**

## Stack

● Backend: Python 3.11 (3.14 target), FastAPI, SQLAlchemy 2.0 async, asyncpg
● Frontend: React 18, TypeScript, Vite, react-router-dom, axios
● Database: PostgreSQL 15 with isolated audit schema
● Auth: JWT (HS256) with bcrypt password hashing
● Infra: Docker Compose, nginx with self-signed TLS, gitleaks plus bandit in CI

**SECTION 04**

## Repository layout

```
backend/                FastAPI application
  app/api/v1/routes/    HTTP route handlers
  app/models/           SQLAlchemy ORM models
  app/schemas/          Pydantic request and response schemas
  app/services/         Domain services (UDL client, ingest, audit)
  app/core/             Cross-cutting concerns (logging, security)
  app/db/               Base, session, engine
  scripts/              Operator CLI scripts (admin bootstrap)
frontend/               React application
  src/api/              Axios client and typed wrappers
  src/components/       Reusable UI components
  src/context/          React context providers
  src/pages/            Route pages
  src/styles/           Design tokens
  src/types/            TypeScript shared types
migrations/             Alembic migration scripts
infra/                  Docker Compose, nginx, TLS certificates
tests/                  pytest suites
docs/                   Documentation (see Documentation section)
.github/workflows/      CI pipelines
```

**SECTION 05**

## Documentation

● [Architecture overview](docs/architecture/overview.md)
● [Architectural decision log](docs/architecture/decision-log.md)
● [Data model](docs/architecture/data-model.md)
● [Security overview](docs/security/overview.md)
● [Audit logging overview](docs/audit/overview.md)
● [Developer setup](docs/developer/setup.md)
● [Operator manual](docs/runbook/operator-manual.md)
● [Analyst training manual](docs/user-handbook/training-manual.md)
● [Phase 1 roadmap](docs/roadmap/phase-1.md)
● [Changelog](CHANGELOG.md)

**SECTION 06**

## Classification

> **STRATEGIC SIGNIFICANCE**
>
> All data processed by this system is confirmed Unclassified (ADR-006). No handling restrictions apply. Commercial cloud and commercial AI APIs are permitted in Phase 2. This document carries the Commercial in Confidence handling marking as an internal Bluestaq Limited business document.

**SECTION 07**

## Bluestaq Limited

This project is delivered by Bluestaq Limited, the UK sovereign subsidiary of Bluestaq LLC. It serves Space Domain Awareness customers across the United Kingdom, Five Eyes, and allied operations.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
