# Changelog

**Classification:** Unclassified
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited

All notable changes to the Daily Operations Dashboard are recorded here. The format follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) without strict adherence. Versions follow [Semantic Versioning](https://semver.org/) once a first tagged release lands; until then, the **Unreleased** section captures work on `main`.

## [Unreleased]

### Added

● End-to-end UDL element-set ingest. `Elset` model, alembic baseline migration, async UDLClient, ingest service with `(udl_id)` upsert, hash-chained audit writes, REST API at `/api/v1/elsets`.
● Analyst-facing Element sets page with filter, pagination, and a manual ingest trigger. Styled against the Bluestaq palette.
● Frontend scaffold: `index.html`, `main.tsx`, `AuthContext` (stubbed pending real auth), `ProtectedRoute`, `Layout`, `Login`, `Dashboard`, axios client, design tokens.
● Audit writer with SHA-256 hash chain and Postgres advisory-lock concurrency control.
● Alembic configuration (`alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`).
● Backend tests covering the UDL client (happy path, 401, 500, non-list responses, missing credentials, epoch formatting) and the UDL-to-model field mapping.
● Documentation: README, architecture overview, data model, security overview, audit overview, developer setup, operator manual, analyst training manual, Phase 1 roadmap, this changelog.
● Decision log entries ADR-007 (UDL ingest pattern), ADR-008 (hash-chained audit), ADR-009 (frontend auth stubbed).

### Changed

● `Settings` now exposes `UDL_USERNAME`, `UDL_PASSWORD`, `UDL_REQUEST_TIMEOUT_SECONDS`, and `UDL_VERIFY_SSL`.
● `.env.example` mirrors the new UDL configuration.

### Fixed

● Frontend `context/AuthContent.tsx` typo replaced with the correctly-named `AuthContext.tsx`.

### Security

● No real credentials are stored in source. `.env*` is gitignored; `.env.example` is the only committed environment file.
● gitleaks runs in CI and as a pre-commit hook.
● bandit at severity `-ll` runs across `backend/app/` in CI and pre-commit.

## Prior history

Captured in git log up to `18fff46` (Merge pull request #1, CI pipeline check).
