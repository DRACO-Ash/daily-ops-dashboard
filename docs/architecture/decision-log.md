**BLUESTAQ LIMITED** | Architectural Decision Log | **COMMERCIAL IN CONFIDENCE**

# Architectural Decision Log

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **HOW TO READ THIS LOG**
>
> Each ADR captures a single decision, its rationale, and (where helpful) alternatives considered and risks accepted. Superseded decisions remain in the log; their status line points to the ADR that replaced them. New ADRs are appended; numbering does not reset.

**ADR-001**

## Python / FastAPI Backend

**Date:** Sprint 1
**Decision:** FastAPI selected as the backend framework.
**Rationale:** Async-native, strong type support via Pydantic, automatic OpenAPI generation, high performance for API-heavy workloads.
**Alternatives considered:** Django REST Framework, rejected due to synchronous defaults and heavier footprint for this use case.

**ADR-002**

## PostgreSQL Database

**Date:** Sprint 1
**Decision:** PostgreSQL 15 as the primary data store.
**Rationale:** Robust, mature, strong support for audit schema isolation, UUID primary keys, and async drivers (asyncpg).

**ADR-003**

## Docker Compose for Local Deployment

**Date:** Sprint 1
**Decision:** Docker Compose used for all local service orchestration.
**Rationale:** Consistent environment across developers; direct migration path to Kubernetes or ECS in Phase 2.

**ADR-004**

## HTTPS Enforced in Local Deployment

**Date:** Sprint 1
**Decision:** Nginx with self-signed TLS certificate used even in local development.
**Rationale:** Avoids security regressions when moving to cloud; forces correct security posture from day one.

**ADR-005**

## Audit Schema Isolation

**Date:** Sprint 1
**Decision:** Audit log stored in a separate PostgreSQL schema with INSERT-only application permissions.
**Rationale:** Prevents accidental or deliberate modification of audit records through the application layer.

**ADR-006**

## Data Classification Confirmed Unclassified

**Date:** Sprint 1
**Decision:** All data processed by this system, including UDL TACREP_NOTSOs, elset records, Mattermost content, ClickUp exports, procedure documents, and analyst inputs, is confirmed Unclassified.
**Rationale:** No handling restrictions apply. Commercial AI APIs (Anthropic Claude) and all major cloud providers are permissible for Phase 2.

**ADR-007**

## UDL Ingest Pattern: Typed Columns plus Raw JSONB

**Date:** 2026-05-27
**Decision:** Every UDL-sourced table models the fields analysts query against as typed columns, and preserves the full UDL payload in a `raw` JSONB column on the same row.
**Rationale:** UDL adds fields over time. Preserving the raw payload means a schema bump on the UDL side never costs us data; typed columns keep the analyst-facing queries fast and well-indexed. The first table that follows this pattern is `elset`. NOTSO, TACREP, and Mattermost ingest will follow the same shape.
**Alternatives considered:** Pure JSONB rows, rejected because typed queries on indexed columns are dramatically faster and let us add database-level constraints where they help.

**ADR-008**

## Hash-Chained Audit Log with Postgres Advisory Lock

**Date:** 2026-05-27
**Decision:** The audit log is tamper-evident via a SHA-256 hash chain. Each row's `entry_hash` covers the previous row's `entry_hash` plus the canonical-JSON serialisation of the new row's payload. Concurrent writes are serialised inside a single transaction via `pg_advisory_xact_lock`.
**Rationale:** The chain detects after-the-fact tampering even by someone with database-level access. The advisory lock prevents two concurrent writers from forking the chain by both reading the same `previous_hash`. Doing this inside the transaction keeps the lock duration short and bounded by the audit write itself.
**Alternatives considered:** Per-row Postgres triggers to compute the hash, rejected to keep the logic in the application layer where it can be unit-tested. External tamper-evident logging service, rejected as overkill for Phase 1.

**ADR-009**

## Frontend Auth Stubbed Pending Backend JWT

**Date:** 2026-05-27
**Status:** Superseded by ADR-010.
**Decision:** The frontend `AuthContext` accepts any non-empty username and stores a stub token in `localStorage`. The axios client and the `ProtectedRoute` gate behave as if the token were real.
**Rationale:** Lets the feature work end-to-end while the real `/api/v1/auth` endpoints are still pending. The contract on the frontend side (token in `Authorization: Bearer ...`, 401 forces logout) matches what the real backend will deliver, so the swap will be small.
**Risks accepted:** Until the real backend auth lands, anyone reaching the host can use the application. The deployed environment is on a sovereign network with network-level access controls in front of nginx, so the application-level gap is acceptable for now. This ADR is to be superseded by ADR-010 (or similar) when the JWT slice lands.

**ADR-010**

## JWT Authentication with Stateless Refresh

**Date:** 2026-05-28
**Status:** Superseded by ADR-011.
**Decision:** Authentication is HS256 JWT bearer tokens issued by `/api/v1/auth/login` and refreshed at `/api/v1/auth/refresh`. Access tokens last 30 minutes; refresh tokens last 7 days. Refresh is stateless: any validly signed refresh token within its expiry window is accepted. Logout is client-side only (delete both tokens from `localStorage`). `get_current_user` enforces a valid access token on protected routes. Supersedes ADR-009.
**Rationale:** Stateless refresh keeps the Phase 1 schema simple (no refresh-token table, no blocklist). The 30-minute access window bounds the blast radius of a stolen token. Bcrypt via `passlib` hashes passwords with per-user salt. Tokens travel in `Authorization: Bearer ...` headers rather than cookies, which removes the standard CSRF vector. The frontend axios client transparently refreshes once on 401 before redirecting to the login page.
**Risks accepted:** A stolen refresh token is valid until expiry (up to 7 days). Mitigations: HTTPS-only transport, refresh tokens never sent to non-auth endpoints, single-retry interceptor that breaks token-loss loops. Real revocation (refresh-token blocklist or a JTI table) is on the Phase 1 backlog for the slice that introduces incident response.
**Operational note:** There is no public sign-up. First user is bootstrapped with `python -m scripts.create_admin --username <name> --password <secret>` from the `backend/` directory. Subsequent users are created by administrators (UI for this is on the backlog).

**ADR-011**

## Refresh-Token Rotation with JTI Block-List

**Date:** 2026-05-28
**Decision:** Refresh tokens carry a `jti` (JWT ID) claim and are tracked in a `revoked_jti` block-list table. `/auth/refresh` rotates: every successful exchange issues a new access AND a new refresh token, and the old refresh token's JTI is added to the block-list. `/auth/logout` now takes the refresh token in its body, validates it, and revokes its JTI; no access-token header is required. Supersedes the stateless-refresh half of ADR-010 (the rest of ADR-010 still applies).
**Rationale:** Rotation gives every refresh token a single-use lifetime, dramatically reducing the value of a stolen refresh token. The block-list lets us forcibly invalidate a specific token without rotating `APP_SECRET_KEY` (which would invalidate every active session). Block-list is preferred over allow-list for Phase 1: smaller table, fewer writes per issue, and the natural-expiry timestamp means we can prune later. The refresh-rotation pattern is also a theft-detection primitive: if the old refresh token shows up again after rotation, that is evidence of replay.
**Risks accepted:** Access tokens still have a 30-minute lifetime gap on logout: we do not revoke the in-flight access token, only the refresh token. If immediate access-token revocation is needed, the operator hammer is still `APP_SECRET_KEY` rotation. A per-request access-token block-list lookup would close that gap at the cost of one DB read per authenticated request, and is on the backlog.
**Operational note:** The `revoked_jti` table grows by one row per logout and one row per refresh-rotation. A pruning job that removes rows past their `expires_at` is on the backlog. Until it lands, table growth is bounded by token TTL: rows older than 7 days are no longer load-bearing.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
