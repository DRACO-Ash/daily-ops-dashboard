**BLUESTAQ LIMITED** | Phase 1 Roadmap | **COMMERCIAL IN CONFIDENCE**

# Phase 1 Roadmap

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **BLUF**
>
> Phase 1 stands up the operational core on a sovereign UK host. UDL ingest, real auth, hash-chained audit, watch-stand UI. The bar for "done" is: an analyst completes a typical watch cycle entirely inside the dashboard, with full audit history, without ad-hoc tooling.

**SECTION 01**

## Phase 1 goals

Phase 1 stands up the operational core on a sovereign UK host:

● End-to-end ingest of the primary UDL data surfaces.
● Real authentication and authorisation.
● Tamper-evident audit on every state change.
● A watch-stand UI analysts actually prefer to the spreadsheets they have now.
● Repeatable local development and a CI gate that catches regressions before they land.

The bar for "done" on Phase 1 is: an analyst can complete a typical watch cycle entirely inside the dashboard, with full audit history, without falling back to ad-hoc tooling.

**SECTION 02**

## Completed

● **Repository skeleton.** Backend (FastAPI), frontend (React/Vite), database (PostgreSQL 15), reverse proxy (nginx), Docker Compose orchestration.
● **Architectural decision log.** ADR-001 to ADR-010 capture the framework, database, deployment, TLS posture, audit isolation, classification, ingest pattern, audit chain, and real JWT auth.
● **CI pipeline.** ruff, mypy, bandit, gitleaks, backend pytest, frontend lint and test. Pre-commit hooks mirror the CI gate.
● **Alembic baseline.** Async-aware env, hand-crafted first migrations for `elset` and `app_user`.
● **UDL element-set ingest, end-to-end.**
  ● Async UDLClient with HTTP Basic auth and typed errors.
  ● Ingest service with `(udl_id)` upsert and chained audit write.
  ● REST API at `/api/v1/elsets` with list, detail, and manual ingest trigger.
  ● Analyst page with filter, pagination, and ingest trigger.
● **Audit log mechanics.** Hash-chained writes serialised by a Postgres advisory lock inside the transaction. Every elset ingest writes a row attributed to the authenticated user and their IP.
● **Real authentication.** `/api/v1/auth/login`, `/auth/refresh`, `/auth/me`. JWT (HS256), 30-minute access tokens, 7-day refresh, stateless. Bcrypt password hashing. Admin bootstrap CLI script. Frontend axios refresh-on-401 interceptor.
● **Frontend.** AuthContext now real, ProtectedRoute, Layout, Login, Dashboard, axios client, design tokens against the Bluestaq palette.
● **Documentation set.** README, architecture overview, data model, security overview, audit overview, developer setup, operator manual, analyst training manual, this roadmap, changelog. Aligned to the Bluestaq Ltd Document Design and Narrative Style Guide v3.

**SECTION 03**

## In progress

● None as of this writing. The next slice has not started.

**SECTION 04**

## Next slice (proposed)

● **Audit emission for auth events.** Issue `auth.user.login`, `auth.user.logout`, and `auth.token.refresh` rows. Action types are already in the taxonomy. Touches `app/api/v1/routes/auth.py` and `app/services/audit.py`.
● **Refresh-token revocation.** A small `revoked_jti` table plus a check in `/auth/refresh`. Removes the "rotate `APP_SECRET_KEY`" hammer for stolen-token scenarios. Lands alongside the incident response runbook.

**SECTION 05**

## Backlog (Phase 1 scope)

Grouped by theme. Order within a theme is the suggested sequence.

### UDL ingest expansion

● NOTSO ingest (mirror the elset pattern).
● TACREP ingest.
● Scheduled background ingest with a configurable cadence per source.
● Multi-page UDL fetch loop so single pulls are not capped by `max_results`.

### Analyst-facing UI

● Element-set detail view that surfaces the full raw payload.
● Sortable columns on the element-set table.
● Saved filters per analyst.
● Cross-source timeline view (combined recent NOTSO, TACREP, elset, Mattermost feed).
● Procedure document upload and reference.

### Identity and access

● User management UI (create, deactivate, role change).
● Role-based gating on routes that need it (admin-only endpoints).
● Forced sign-out workflow integrated with the refresh-token revocation table.

### Audit and observability

● CLI utility (`audit-verify`) that walks the chain and reports any breaks.
● Audit export workflow with its own `audit.export.run` action type.
● Centralised log shipping (filebeat or vector to a sink).
● Application metrics (Prometheus or OpenTelemetry).
● Health endpoint richer than `{"status":"ok"}` (component-level breakdown).

### Platform and tooling

● Real database backups.
● Route-level integration tests against a real Postgres test database (testcontainers in CI).
● Dependabot or equivalent for dependency updates.
● Automated TLS certificate provisioning for non-local environments.

### Documentation

● Threat model document with STRIDE breakdown per surface.
● Incident response runbook once forced sign-out exists.
● Per-data-source ingest runbook (one per UDL endpoint).

**SECTION 06**

## Phase 2 outlook

Phase 2 lifts the dashboard from a sovereign single-host deployment to an allied multi-tenant capability.

● Hosting on Kubernetes or Amazon ECS.
● Managed PostgreSQL with point-in-time recovery.
● Cloud secret manager replacing `.env`.
● AI-assisted analyst triage via Anthropic Claude (permitted because data is Unclassified per ADR-006).
● Multi-tenant data partitioning if the customer model demands it.

Phase 2 scope will be expanded once Phase 1 ships.

**SECTION 07**

## Review cadence

This roadmap is reviewed at the end of every sprint. Owners update the **Completed** and **In progress** sections in real time as work moves.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
