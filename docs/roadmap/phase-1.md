**BLUESTAQ LIMITED** | Phase 1 Roadmap | **COMMERCIAL IN CONFIDENCE**

# Phase 1 Roadmap

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.3
**Last updated:** 2026-05-28

> **BLUF**
>
> Phase 1 stands up the operational core on a sovereign UK host. UDL ingest (elsets + NOTSOs), real JWT auth with refresh rotation, hash-chained audit with viewer, request-id-correlated logs, watch-stand UI. The bar for "done" is: an analyst completes a typical watch cycle entirely inside the dashboard, with full audit history, without ad-hoc tooling. Most of that bar is now met.

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
● **Architectural decision log.** ADR-001 to ADR-011 capture framework, database, deployment, TLS, audit isolation, classification, ingest pattern, audit chain, JWT auth, and refresh rotation.
● **CI pipeline.** ruff, ruff-format, mypy, bandit, gitleaks, backend pytest with `pytest-cov` (40% floor), frontend eslint and prettier format check. Pre-commit hooks mirror the CI gate.
● **Alembic baseline.** Async-aware env, hand-crafted migrations through `0005_rename_notso` covering elset, app_user, revoked_jti, and notification (the latter renamed from notso once the combined UDL endpoint behaviour was confirmed).
● **UDL element-set ingest, end-to-end.** Async UDLClient with HTTP Basic auth, ingest service with `(udl_id)` upsert and chained audit write, REST API at `/api/v1/elsets` with list/detail/ingest, analyst page with filter, pagination, sortable columns, clickable rows leading to a detail view.
● **UDL notification ingest, end-to-end.** UDL serves Tactical Reports and Notices to Space Operators through a single `/notification` endpoint under `msgType=TACREP_NOTSO`; the surface is named accordingly. `UDLClient.get_notifications` takes `msg_type`, `created_at_gte`, `data_mode`, `source`, `max_results`. Ingest service mirrors the elset dedupe and audit pattern. Routes at `/api/v1/notifications`; analyst page sortable on UDL created time, with msg-type filter and detail view. The earlier "NOTSO" naming (and the matching `notso` table) was renamed to `notification` at migration `0005_rename_notso`.
● **Real authentication.** `/api/v1/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`. JWT (HS256), 30-minute access tokens, 7-day refresh, JTI-tracked. Bcrypt password hashing. Admin bootstrap CLI script. Frontend axios refresh-on-401 interceptor that updates the rotated refresh token.
● **Refresh-token rotation and JTI block-list (ADR-011).** Every refresh issues a new pair and revokes the old JTI. `/auth/logout` revokes the JTI carried in the body. Stolen-token reuse is detected and rejected with `revoked_token`.
● **Audit log mechanics.** Hash-chained writes serialised by a Postgres advisory lock inside the transaction. Every ingest and every auth event (login, logout, refresh) writes a row attributed to the authenticated user and source IP.
● **Audit log viewer.** `GET /api/v1/audit` role-gated to operator and admin, paginated, filterable. Dashboard **Audit log** page surfaces the full chain to operators and admins.
● **Observability.** `RequestIDMiddleware` attaches an `X-Request-ID` per request, honoured from inbound or generated, and every backend log line carries the active `request_id`. `GET /api/v1/health/detailed` returns component-level status (database, UDL credentials), version, and environment.
● **Dashboard surface cards.** Live counts and most-recent timestamps for each data source, fetched in parallel on page load.
● **Code quality.** Prettier configured and enforced in CI alongside eslint. `pytest-cov` enforces a 40% floor (intent to ratchet up).
● **Documentation set.** README, architecture overview, data model, security overview, audit overview, developer setup, operator manual, analyst training manual, this roadmap, changelog. Aligned to the Bluestaq Ltd Document Design and Narrative Style Guide v3.

**SECTION 03**

## In progress

● None as of this writing. The next slice has not started.

**SECTION 04**

## Next slice candidates

In rough order of value, smallest natural slices first:

● **Coverage ratchet.** Add tests for the elset and notification ingest services (the upsert path) and the token revocation service, bump the `--cov-fail-under` to 60%. Smallest commit; biggest assurance gain per line.
● **Username-enumeration mitigation.** Run a dummy `verify_password` on the unknown-user path so the timing matches the wrong-password path. Single-file change to `auth.py` with one new test.
● **Multi-page UDL fetch loop.** Loop until the source returns fewer than `max_results` records. Removes the single-call cap on ingest.
● **Scheduled background ingest.** APScheduler or a Celery-style worker that pulls every N minutes per source. Audited with a `system` user_id sentinel.
● **Additional UDL surfaces.** Conjunctions, sensor data, or other notification message types as the watch demands. Same shape as the existing surfaces.

**SECTION 05**

## Backlog (Phase 1 scope)

Grouped by theme.

### UDL ingest expansion

● Additional notification message types beyond `TACREP_NOTSO` if the watch picks up others worth surfacing.
● Other UDL data surfaces (conjunctions, sensor data) as the watch demands.
● Scheduled background ingest with a configurable cadence per source.
● Multi-page UDL fetch loop so single pulls are not capped by `max_results`.

### Analyst-facing UI

● Saved filters per analyst.
● Cross-source timeline view (combined recent notifications, elsets, Mattermost feed).
● Procedure document upload and reference.

### Identity and access

● User management UI (create, deactivate, role change).
● Per-user "revoke all my tokens" admin action against the `revoked_jti` table.
● Wider role-based gating once roles have surfaces to gate.

### Audit and observability

● CLI utility (`audit-verify`) that walks the hash chain and reports any breaks.
● "Verify the chain" button in the audit log UI.
● Audit export workflow with its own `audit.export.run` action type.
● Pruning job for `revoked_jti` and old audit rows past their retention window.
● Structured (JSON) logging for log aggregator ingestion.
● Application metrics (Prometheus or OpenTelemetry).
● Centralised log shipping (filebeat or vector to a sink).

### Platform and tooling

● Real database backups.
● Route-level integration tests against a real Postgres test database (testcontainers in CI).
● Dependabot or equivalent for dependency updates.
● Automated TLS certificate provisioning for non-local environments.

### Documentation

● Threat model document with STRIDE breakdown per surface.
● Incident response runbook once the per-user revoke action exists.
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
