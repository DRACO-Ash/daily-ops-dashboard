**BLUESTAQ LIMITED** | Architecture Overview | **COMMERCIAL IN CONFIDENCE**

# Architecture Overview

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **BLUF**
>
> Browser-based watch-stand surface for SDA analysts, backed by FastAPI and PostgreSQL behind nginx TLS. UDL element sets and notifications (TACREP_NOTSO) are live; Mattermost, ClickUp, and procedure documents will follow the same pattern. Every state change is audit-logged with a tamper-evident hash chain.

**SECTION 01**

## Intent

A single browser-based surface for SDA watch analysts that brings UDL records, Mattermost activity, ClickUp exports, procedure documents, and analyst notes together. Every action is audit-logged. The architecture is designed for sovereign UK deployment now, with a clean path to a multi-tenant allied deployment in Phase 2.

**SECTION 02**

## System context

```
   ┌──────────────────────┐        ┌──────────────────────┐
   │  Unified Data        │        │  Mattermost          │
   │  Library (UDL)       │        │  (Phase 1 backlog)   │
   └──────────┬───────────┘        └──────────┬───────────┘
              │ HTTPS / Basic auth            │
              ▼                                ▼
   ┌──────────────────────────────────────────────────────┐
   │  Backend (FastAPI)                                   │
   │  ● Ingest services      ● Audit service              │
   │  ● REST API (/api/v1)   ● JWT auth                   │
   └────────────┬─────────────────────────────┬───────────┘
                │ async SQL                    │ JSON
                ▼                              ▼
   ┌──────────────────────────┐   ┌──────────────────────┐
   │  PostgreSQL 15           │   │  Frontend (React)    │
   │  ● public schema (data)  │   │  ● Vite dev server   │
   │  ● audit schema (log)    │   │  ● axios via /api    │
   └──────────────────────────┘   └──────────┬───────────┘
                                              │
                                              ▼
                                  ┌──────────────────────┐
                                  │  Analyst browser     │
                                  │  via nginx TLS       │
                                  └──────────────────────┘
```

**SECTION 03**

## Components

### Backend (FastAPI)

The backend is structured around four layers:

● **API layer** ([backend/app/api/v1/routes/](../../backend/app/api/v1/routes/)) holds HTTP route handlers. Each handler is thin and delegates to a service.
● **Service layer** ([backend/app/services/](../../backend/app/services/)) holds domain logic. The UDL client, the ingest pipelines, and the audit writer all live here.
● **Schema layer** ([backend/app/schemas/](../../backend/app/schemas/)) holds Pydantic models for request validation and response serialisation.
● **Model layer** ([backend/app/models/](../../backend/app/models/)) holds SQLAlchemy ORM definitions.

Cross-cutting concerns sit in [backend/app/core/](../../backend/app/core/) (logging, security) and [backend/app/db/](../../backend/app/db/) (engine, session).

### Frontend (React)

The frontend is a single-page application served by Vite in development and built into static assets for production. Authentication state flows through an `AuthContext` provider. Protected routes redirect to `/login` when the JWT is absent. The axios client at [frontend/src/api/client.ts](../../frontend/src/api/client.ts) injects the bearer token, transparently refreshes once on 401, and triggers a logout on refresh failure.

### Database (PostgreSQL 15)

Two schemas:

● `public` holds operational data (`elset`, `notification`, `app_user`; later `mattermost_message`, `procedure_doc`).
● `audit` holds the tamper-evident audit log. The application has INSERT-only permissions on this schema (see ADR-005).

### Reverse proxy (nginx)

nginx terminates TLS (self-signed in local development; real certificates in deployed environments). It routes `/api/*` to the backend container and everything else to the frontend container. TLS is enforced even in local development to prevent security regressions when moving to deployed environments (see ADR-004).

**SECTION 04**

## Data flow: UDL element-set ingest

1. Analyst clicks **Pull from UDL** on the Element Sets page, providing an "epoch since" timestamp and optional satellite number.
2. Frontend POSTs to `/api/v1/elsets/ingest` with the request body and the bearer token.
3. `get_current_user` validates the access token and loads the user.
4. Route handler instantiates a `UDLClient` (HTTP Basic auth from environment) and calls `ingest_elsets`.
5. Ingest service calls UDL's `/elset` endpoint, receives a JSON array of records, maps UDL camelCase to model snake_case, and upserts on `udl_id` via `INSERT ... ON CONFLICT DO UPDATE`.
6. Ingest service writes a chained audit entry inside the same transaction with the authenticated user's id and IP address, serialised via a Postgres advisory lock.
7. Response includes counts: pulled, inserted, updated, skipped.
8. Frontend reloads the table and surfaces the result.

**SECTION 05**

## Deployment topology

### Phase 1 (current)

● Single Docker Compose stack on a sovereign host.
● Containers: `backend`, `frontend`, `db`, `nginx`.
● Internal Docker network isolates `db` from external traffic; only `nginx` is published.

### Phase 2 (planned)

● Kubernetes or Amazon ECS hosting.
● Managed PostgreSQL (RDS-equivalent) with point-in-time recovery.
● Secrets in cloud secret manager rather than `.env` files.
● Optional integration with commercial AI APIs (Anthropic Claude) for analyst triage. Permitted because all processed data is Unclassified (see ADR-006).

**SECTION 06**

## Security boundaries

● Internet boundary: nginx with TLS. Only `/api/*` and the static frontend are exposed.
● Backend to database: confined to the internal Docker network.
● Backend to UDL: outbound HTTPS with Basic auth from environment variables.
● Audit schema: separate schema with INSERT-only application permissions.
● Application boundary: JWT bearer tokens on every `/elsets/*` route; access tokens last 30 minutes (ADR-010).

A fuller treatment is in [docs/security/overview.md](../security/overview.md).

**SECTION 07**

## See also

● [Architectural decision log](decision-log.md) for the why behind every choice on this page.
● [Data model](data-model.md) for table and column detail.
● [Audit logging overview](../audit/overview.md) for the hash-chain mechanics.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
