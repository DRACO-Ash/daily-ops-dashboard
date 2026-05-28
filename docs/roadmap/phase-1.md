# Phase 1 Roadmap

**Classification:** Unclassified
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.1
**Last updated:** 2026-05-27

## Phase 1 goals

Phase 1 stands up the operational core on a sovereign UK host:

● End-to-end ingest of the primary UDL data surfaces.
● Real authentication and authorisation.
● Tamper-evident audit on every state change.
● A watch-stand UI analysts actually prefer to the spreadsheets they have now.
● Repeatable local development and a CI gate that catches regressions before they land.

The bar for "done" on Phase 1 is: an analyst can complete a typical watch cycle entirely inside the dashboard, with full audit history, without falling back to ad-hoc tooling.

## Completed

● **Repository skeleton.** Backend (FastAPI), frontend (React/Vite), database (PostgreSQL 15), reverse proxy (nginx), Docker Compose orchestration.
● **Architectural decision log.** ADR-001 to ADR-009 capture the framework, database, deployment, TLS posture, audit isolation, classification, and recent ingest and audit choices.
● **CI pipeline.** ruff, mypy, bandit, gitleaks, backend pytest, frontend lint and test. Pre-commit hooks mirror the CI gate.
● **Alembic baseline.** Async-aware env, hand-crafted first migration for the `elset` table.
● **UDL element-set ingest, end-to-end.**
  ● Async UDLClient with HTTP Basic auth and typed errors.
  ● Ingest service with `(udl_id)` upsert and chained audit write.
  ● REST API at `/api/v1/elsets` with list, detail, and manual ingest trigger.
  ● Analyst page with filter, pagination, and ingest trigger.
● **Audit log mechanics.** Hash-chained writes serialised by a Postgres advisory lock inside the transaction.
● **Frontend scaffold.** AuthContext (stubbed), ProtectedRoute, Layout, Login, Dashboard, axios client, design tokens against the Bluestaq palette.

## In progress

● None as of this writing. The next slice has not started.

## Next slice (proposed)

● **Backend auth.** `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/logout`. Bcrypt password hashing. JWT issuance with the existing settings. Replace the stub auth in `AuthContext.tsx`. Wire a JWT dependency on all mutating routes, especially `POST /api/v1/elsets/ingest`.
● **Audit user attribution.** Once auth is real, every audit row carries the authenticated `user_id` and `ip_address`.

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
● Incident response runbook once real user sessions exist.
● Per-data-source ingest runbook (one per UDL endpoint).

## Phase 2 outlook

Phase 2 lifts the dashboard from a sovereign single-host deployment to an allied multi-tenant capability.

● Hosting on Kubernetes or Amazon ECS.
● Managed PostgreSQL with point-in-time recovery.
● Cloud secret manager replacing `.env`.
● AI-assisted analyst triage via Anthropic Claude (permitted because data is Unclassified per ADR-006).
● Multi-tenant data partitioning if the customer model demands it.

Phase 2 scope will be expanded once Phase 1 ships.

## Review cadence

This roadmap is reviewed at the end of every sprint. Owners update the **Completed** and **In progress** sections in real time as work moves.
