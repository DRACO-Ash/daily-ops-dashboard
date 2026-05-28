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
