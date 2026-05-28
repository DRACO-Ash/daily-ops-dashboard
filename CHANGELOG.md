**BLUESTAQ LIMITED** | Changelog | **COMMERCIAL IN CONFIDENCE**

# Changelog

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

All notable changes to the Daily Operations Dashboard are recorded here. The format follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) without strict adherence. Versions follow [Semantic Versioning](https://semver.org/) once a first tagged release lands; until then, the **Unreleased** section captures work on `main`.

## [Unreleased]

### Added

● **Audit log viewer.** New `GET /api/v1/audit` endpoint role-gated to `operator` and `admin` via the existing `require_role` factory. Filters by `action_type`, `user_id`, `since`, and `until`; paginated. Frontend Audit log page shows timestamp, action, entity, user, IP, and the parsed detail payload. AuthContext now fetches `/auth/me` on mount and exposes the current `user`; Layout filters the side nav by role so the audit link only appears for operators and admins.
● **UI polish.** Sortable column headers on the Element sets and NOTSOs list pages (click to toggle direction, with an arrow indicator). Detail pages at `/elsets/:id` and `/notsos/:id` showing parsed fields, the TLE for elsets, the description for NOTSOs, and the full raw UDL payload. Rows in the list pages are clickable and route through to the detail. Dashboard refreshed with live count cards for each surface (Element sets, NOTSOs) including the most recent record's label and timestamp.
● Backend list routes now accept `sort_by` and `sort_dir` query parameters (whitelisted via `Literal` types, validated by FastAPI). Defaults preserve previous behaviour (elsets by epoch desc, NOTSOs by effective_from desc).
● Reusable `SortableHeader` component, design tokens for sortable headers, clickable rows, detail-grid, raw-json, TLE block, NOTSO description block, and the dashboard surface cards.
● **NOTSO ingest, end-to-end.** New `Notso` model and migration `0004_create_notso`, `UDLClient.get_notsos()`, `ingest_notsos` service mirroring the elset pattern, REST API at `/api/v1/notsos` (list with `msg_type` and `sat_no` filters, detail, and a manual ingest trigger). Frontend Notsos page with the same shape as Element sets. Action type `udl.notso.ingest` is now Active in the audit taxonomy.
● `UDLClient` factored to share a single `_get_list` helper between `get_elsets` and `get_notsos`. No behaviour change for the existing elset path.
● Backend tests for the NOTSO UDL-to-model mapping (full record, datetime parsing across `effectiveFrom`/`effectiveUntil`/`expirationTime`/`createdAt`, raw payload preservation, missing-id skip, fallback aliases for `text` and `expirationTime`).
● Refresh-token rotation and JTI block-list (ADR-011). Every JWT now carries a `jti` claim. `POST /auth/refresh` rotates: it issues a new access AND a new refresh token and revokes the old refresh-token JTI in the `revoked_jti` table. A reused old refresh token is rejected with audit reason `revoked_token`. New alembic migration `0003_create_revoked_jti` adds the block-list table. New `app/services/token_revocation.py` exposes `is_revoked` and `revoke`.
● `POST /auth/logout` now takes the refresh token in its body (no access-token header required) and revokes its JTI. The audit row carries success or one of `invalid_token`, `missing_claim`, `malformed_subject`, `already_revoked`.
● Audit-log emission for auth events. `POST /auth/login` writes `auth.user.login` rows for both success and the three failure modes (unknown user, inactive user, wrong password); `POST /auth/refresh` writes `auth.token.refresh` rows for success and the new revoked-token failure reason. Action types are Active in the audit taxonomy.
● Real JWT authentication. `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh` issue HS256 tokens (30-minute access, 7-day refresh). `GET /api/v1/auth/me` returns the current user. Supersedes the frontend auth stub.
● `User` model with role enum (analyst / operator / admin), bcrypt password hashing, alembic migration `0002_create_user`.
● `get_current_user` dependency wired onto every `/elsets` route. `POST /elsets/ingest` now records the authenticated user's `id` and IP address in the audit log.
● Admin bootstrap script at `backend/scripts/create_admin.py`. Run via `python -m scripts.create_admin --username <name> --password <secret>` from the `backend/` directory.
● Frontend axios refresh-on-401 interceptor; `AuthContext` now talks to the real backend.
● Backend tests for password hashing, JWT round-trip, login flow (happy path, wrong password, unknown user, inactive user), `/auth/me` token validation, refresh, and the auth gate on `/elsets/ingest`.
● Decision log ADR-010 (JWT authentication with stateless refresh, supersedes ADR-009).
● End-to-end UDL element-set ingest. `Elset` model, alembic baseline migration, async UDLClient, ingest service with `(udl_id)` upsert, hash-chained audit writes, REST API at `/api/v1/elsets`.
● Analyst-facing Element sets page with filter, pagination, and a manual ingest trigger. Styled against the Bluestaq palette.
● Frontend scaffold: `index.html`, `main.tsx`, `ProtectedRoute`, `Layout`, `Login`, `Dashboard`, axios client, design tokens.
● Audit writer with SHA-256 hash chain and Postgres advisory-lock concurrency control.
● Alembic configuration (`alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`).
● Backend tests covering the UDL client (happy path, 401, 500, non-list responses, missing credentials, epoch formatting) and the UDL-to-model field mapping.
● Documentation set: README, architecture overview, data model, security overview, audit overview, developer setup, operator manual, analyst training manual, Phase 1 roadmap, this changelog.
● Decision log entries ADR-007 (UDL ingest pattern), ADR-008 (hash-chained audit), ADR-009 (frontend auth stubbed, now superseded).

### Changed

● `POST /auth/refresh` response is now `TokenResponse` (both `access_token` and `refresh_token`) instead of `RefreshResponse`. Frontend stores the new refresh token returned by the server.
● `POST /auth/logout` now takes a body `{refresh_token: "..."}` instead of relying on the access-token header. Supersedes the bearer-only logout from the prior auth-events slice.
● **Documentation aligned to the Bluestaq Ltd Document Design and Narrative Style Guide v3 (March 2026).** Every doc now carries the brand-banner top line, the metadata block, `**SECTION NN**` eyebrows before every H2 (or `**ADR-NNN**` in the decision log), copper and blue callout patterns where they earn their place, and the standard footer line. Version bumped to 0.2 across the set.
● `Settings` now exposes `UDL_USERNAME`, `UDL_PASSWORD`, `UDL_REQUEST_TIMEOUT_SECONDS`, and `UDL_VERIFY_SSL`.
● `.env.example` mirrors the new UDL configuration.

### Removed

● Frontend stub authentication (any-non-empty-username accepted). Superseded by real backend JWT.

### Fixed

● Frontend `context/AuthContent.tsx` typo replaced with the correctly-named `AuthContext.tsx`.

### Security

● Bcrypt password hashing via `passlib`. JWT signed with `APP_SECRET_KEY` using HS256. Tokens travel in the `Authorization` header, never in cookies.
● No real credentials are stored in source. `.env*` is gitignored; `.env.example` is the only committed environment file.
● gitleaks runs in CI and as a pre-commit hook.
● bandit at severity `-ll` runs across `backend/app/` in CI and pre-commit.

## Prior history

Captured in git log up to `18fff46` (Merge pull request #1, CI pipeline check).

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
