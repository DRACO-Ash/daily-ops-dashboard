# Security Overview

**Classification:** Unclassified
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.1
**Last updated:** 2026-05-27

## Posture

Sovereign UK deployment serving SDA analysts. All data processed is confirmed Unclassified (ADR-006), so the controls below are aimed at integrity, audit, and operational hygiene rather than at protecting classified material. The security model assumes a trusted operator network in front of nginx, with application-level controls layered behind that.

## Data classification

● **Unclassified.** Confirmed by ADR-006. Applies to UDL TACREP_NOTSOs, elset records, Mattermost content, ClickUp exports, procedure documents, and analyst inputs.
● No handling caveats apply. Commercial cloud providers and commercial AI APIs (Anthropic Claude) are permitted in Phase 2.

When new data sources are added, ADR-006 must be re-evaluated. Any source carrying a higher classification must be rejected at ingest until the system is uplifted.

## Authentication

### Current state (Phase 1)

● Frontend `AuthContext` is stubbed. Any non-empty username succeeds and stores a `dev-token` placeholder in `localStorage`. See ADR-009.
● Backend routes are not behind an auth dependency. The audit writer accepts a `user_id` argument, but routes do not yet supply one.
● Acceptable today because deployed environments sit behind network-level access control on a sovereign network.

### Planned (next slice)

● Real JWT issuance via `/api/v1/auth/login`. Passwords hashed with bcrypt (`passlib`).
● `Authorization: Bearer <jwt>` on every protected route.
● Token expiry: 30 minutes for access, 7 days for refresh (see `Settings.jwt_*`).
● Application-level deny by default for any route that mutates data, especially `POST /api/v1/elsets/ingest`.

## Authorisation

Not yet implemented. The route layer will gain a role-aware dependency once JWT auth lands. Planned roles:

● `analyst` — read all surfaces, trigger ingests.
● `operator` — analyst capabilities plus configuration changes.
● `admin` — operator capabilities plus user management.

## Audit logging

Every state-changing action writes an audit entry. The audit log is tamper-evident via a SHA-256 hash chain (ADR-008). Full details in [docs/audit/overview.md](../audit/overview.md).

## Transport security

● TLS terminates at nginx. Self-signed certificate in local development, real certificates in deployed environments.
● TLS is enforced even locally (ADR-004) to prevent posture regressions when moving to deployed environments.
● `UDL_VERIFY_SSL` defaults to `true`. The escape hatch exists for corporate-proxy dev setups; do not disable in deployed environments.
● The internal Docker network `internal` is `driver: bridge` with `internal: true`, so `db` is unreachable from outside the host.

## Secrets management

### Current state

● Local development uses a `.env` file. `.env*` is gitignored except for `.env.example`.
● CI injects environment variables directly (see [.github/workflows/ci.yml](../../.github/workflows/ci.yml)). No real credentials are checked in.
● The `gitleaks` pre-commit hook and CI job scan the repository for accidental secret leaks on every commit and pull request.

### Planned (Phase 2)

● Cloud secret manager (AWS Secrets Manager, Azure Key Vault, or equivalent) replaces `.env` in deployed environments.
● Per-service IAM identities replace the shared `.env` password approach.

## Dependency and code scanning

CI gates and pre-commit hooks ([.pre-commit-config.yaml](../../.pre-commit-config.yaml)):

● **ruff** for lint, including import sorting (`I001`) and `ruff-format` for formatting.
● **mypy** for type checking on `backend/app/`.
● **bandit** at severity `-ll` for Python security smell detection.
● **gitleaks** for secret patterns.

CI workflow ([.github/workflows/ci.yml](../../.github/workflows/ci.yml)):

● The above, plus `pytest tests/backend` for backend test execution.
● `npm run lint` and `npm run test` (vitest) for the frontend.
● `gitleaks/gitleaks-action@v2` for repository-wide secret scanning on every pull request.

## Threat surface

| Vector | Mitigation |
|--------|-----------|
| External attacker reaches the application | nginx is the only public endpoint. Backend and DB are on an internal-only Docker network. TLS is enforced. |
| Compromised analyst credentials | Audit log records every action. Hash chain detects retrospective tampering. Token expiry limits blast radius. (Effective once JWT slice lands.) |
| Compromised UDL credentials | Stored in environment variables, not in source. Phase 2 moves these to a secret manager. Compromise of read-only UDL credentials does not enable writes against our system. |
| SQL injection | SQLAlchemy parameterises every query. No raw string concatenation into SQL. |
| Cross-site scripting (XSS) | React escapes by default. We do not use `dangerouslySetInnerHTML`. |
| Cross-site request forgery (CSRF) | Once JWT auth lands, tokens travel in the `Authorization` header rather than a cookie, removing the standard CSRF vector. |
| Supply-chain compromise | Pinned versions in `requirements.txt` and `package-lock.json`. Dependabot or equivalent is a Phase 2 add. |
| Insider modifies audit log | Application role has INSERT-only permissions on the audit schema. Hash chain detects modifications even by a DBA who bypasses the application. |
| Accidental commit of secrets | gitleaks at pre-commit and in CI. `.env` family in `.gitignore`. |

## Incident response

Phase 1 has no formal incident response runbook. Operational response is owned by the on-call engineer. When `/api/v1/health` returns non-200 or the dashboard is unreachable, follow [docs/runbook/operator-manual.md](../runbook/operator-manual.md).

A formal incident response runbook will land alongside the JWT auth slice, when there are real user sessions to revoke.

## Review

This document is reviewed when a security-relevant change lands. Triggers include:

● New ingest sources.
● Authentication or authorisation changes.
● Network or infrastructure changes.
● New external integrations (AI APIs, cloud providers).
● Findings from a penetration test or audit.
