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

● **Mattermost archive (ported from `mattermost_channel_pull`).** With `MATTERMOST_TEAM` set, the ingest discovers every open or private channel the bot (dok.bot) belongs to, skipping archived channels and direct messages. The first cycle for a channel walks its full history backwards with a `before` cursor, resuming across cycles (`MATTERMOST_BACKFILL_PAGES_PER_CYCLE`); later cycles pull only posts created or modified since the channel's watermark. Edits replace the stored text only when newer, deletions set `deleted_at` and keep the last text, and replies record `root_id`. Author names are looked up in batches. The client retries 429 and 5xx with `Retry-After`. Migration `0016_mattermost_archive` adds the revision columns and `mattermost_channel_state`. Deleted posts are hidden from the messages list (unless `include_deleted=true`) and from the assistant.

● **Bluestaq App Store packaging.** Root multi-stage `Dockerfile` builds the React bundle and runs FastAPI, which now serves the SPA alongside `/api/v1` (`app/core/spa.py`) with CSP and security headers. `deploy/entrypoint.sh` retries migrations until Postgres is ready, optionally bootstraps an admin, and binds `$PORT` (default 8080). Config accepts the add-on `PG*` variables and stores procedures under `STORAGE_MOUNT_PATH`. `scripts/package-appstore.sh` builds the upload zip; `deploy/APPSTORE.md` covers submission.

### Security

● Replaced `python-jose` (unfixed `ecdsa` advisory) with PyJWT. Bumped `fastapi` (and Starlette), `python-multipart`, `cryptography` and `axios` past known CVEs. Removed unused `aiopg`.

### Fixed

● Frontend production build: restored the `SortDirection` type lost with the Element Sets removal; `tsc` had been failing. CI now runs `npm run build`.
● Alembic migrations take a Postgres advisory lock so concurrent replicas do not race.

● **`scripts\dev.ps1` one-file local deploy and run.** Idempotent: creates `.env` from `.env.example` with a fresh `APP_SECRET_KEY` if missing, generates a self-signed TLS certificate via docker if `infra/certs/` is empty, brings up the full stack, waits for the database, applies pending alembic migrations inside the backend container, bootstraps the first admin user if `app_user` is empty, and tails backend logs. Supports `-Down`, `-Restart`, `-Reset` (destructive), `-NoLogs`, `-RegenerateCerts`. Admin credentials can be supplied via `-AdminUsername`/`-AdminPassword` flags or `$env:ADMIN_USERNAME`/`$env:ADMIN_PASSWORD` for non-interactive runs.
● **Real TACREP_NOTSO shape support.** UDL nests the interesting fields inside `msgBody`; mapper now extracts `NOTSO` (notice identifier), `Event_Class`, `Event_Type`, `Event_Id`, `Status` (OPEN/CLOSED), `Event_Description`, `Company_Name`, `NOTSO_Link`, `Publish_Date`, and the `SatIds` array. Top-level envelope fields (`createdBy`, `origNetwork`, `classificationMarking`, etc.) are now captured too. Migration `0006_notif_msgbody` adds eleven new typed columns plus four query indexes (`notso_identifier`, `status`, `event_type`, `publish_date`).
● **Notifications page redesign.** List view now shows Notice / Status / Type / Event class / Sat IDs / UDL created. Status filter (OPEN/CLOSED), event-type filter, and status indicator pills. Ingest form defaults `Source` to `JCO` to match the production query.
● **Notification detail view.** New sections for Status, Identification (including the `NOTSO_Link` URL to the JCO source page), Timing, Associated objects (rendering the full `SatIds` array), Event description (preformatted), and Source artefacts (parses `NOTSO_Image_Metadata` and renders clickable links to the underlying assets).
● Single-sat convenience: when `SatIds` has exactly one numeric value, `sat_no` is populated so existing filter and sort paths still work; multi-sat notices populate `sat_ids` only.

### Changed

● `infra/docker-compose.yml` now mounts the repo root at `/workspace` on the backend container so alembic can find `alembic.ini` and `migrations/` (which live at the repo root, not under `backend/`). No effect on the production-time backend (uvicorn still runs from `/app`).
● `frontend/vite.config.ts` pins the dev server to port `3000` to match the `proxy_pass http://frontend:3000;` line in `infra/nginx/nginx.conf`. Previously vite defaulted to `5173` and the nginx proxy would have failed; fix went unnoticed because nobody had brought the full stack up locally yet.

● **`notso` → `notification` rename.** UDL serves Tactical Reports (TACREP) and Notices to Space Operators (NOTSO) through a single `/notification` endpoint under `msgType=TACREP_NOTSO`; the earlier naming treated them as separate surfaces, which was wrong. Alembic migration `0005_rename_notso` renames the table, its indexes, and the unique constraint. Backend model, schemas, ingest service, routes, UDL client method, and audit action type (`udl.notso.ingest` → `udl.notification.ingest`) all renamed accordingly. Frontend page, types, API wrapper, navigation label, and route URL move from `/notsos` to `/notifications`. UDL endpoint corrected from `/notso` to `/notification`. New ingest parameters (`msg_type`, `created_at_gte`, `data_mode`, `source`, `max_results`) match the example URL used in production. `msg_type` defaults to `TACREP_NOTSO`.

### Added

● **Observability and code-quality bar.** Every HTTP response now carries an `X-Request-ID` header (honoured from inbound or generated as a UUID), and every backend log line includes the active `request_id` so traces can be correlated end-to-end. New `GET /api/v1/health/detailed` returns a component breakdown (database connectivity, UDL credential configuration) plus version and environment. Coverage is enforced in CI via `pytest-cov` with a 40% floor (initial bar, will ratchet up). Frontend code is now governed by Prettier; a `format:check` step runs in CI alongside the existing eslint step.
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
