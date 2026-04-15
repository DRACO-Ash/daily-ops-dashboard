# Architectural Decision Log

## ADR-001 — Python / FastAPI Backend
**Date:** Sprint 1
**Decision:** FastAPI selected as the backend framework.
**Rationale:** Async-native, strong type support via Pydantic, automatic OpenAPI generation, high performance for API-heavy workloads.
**Alternatives considered:** Django REST Framework — rejected due to synchronous defaults and heavier footprint for this use case.

## ADR-002 — PostgreSQL Database
**Date:** Sprint 1
**Decision:** PostgreSQL 15 as the primary data store.
**Rationale:** Robust, mature, strong support for audit schema isolation, UUID primary keys, and async drivers (asyncpg).

## ADR-003 — Docker Compose for Local Deployment
**Date:** Sprint 1
**Decision:** Docker Compose used for all local service orchestration.
**Rationale:** Consistent environment across developers; direct migration path to Kubernetes or ECS in Phase 2.

## ADR-004 — HTTPS Enforced in Local Deployment
**Date:** Sprint 1
**Decision:** Nginx with self-signed TLS certificate used even in local development.
**Rationale:** Avoids security regressions when moving to cloud; forces correct security posture from day one.

## ADR-005 — Audit Schema Isolation
**Date:** Sprint 1
**Decision:** Audit log stored in a separate PostgreSQL schema with INSERT-only application permissions.
**Rationale:** Prevents accidental or deliberate modification of audit records through the application layer.

## ADR-006 — Data Classification Confirmed Unclassified
**Date:** Sprint 1
**Decision:** All data processed by this system — UDL TACREP_NOTSOs, elset records, Mattermost content, ClickUp exports, procedure documents, and analyst inputs — is confirmed Unclassified.
**Rationale:** No handling restrictions apply. Commercial AI APIs (Anthropic Claude) and all major cloud providers are permissible for Phase 2.