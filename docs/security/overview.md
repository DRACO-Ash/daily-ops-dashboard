**BLUESTAQ LIMITED** | Security Overview | **COMMERCIAL IN CONFIDENCE**

# Security Overview

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **BLUF**
>
> Sovereign UK deployment carrying Unclassified data. Controls aim at integrity, audit, and operational hygiene rather than protecting classified material. JWT-gated routes, tamper-evident audit chain, TLS-everywhere, scanned dependencies, scanned secrets.

**SECTION 01**

## Posture

Sovereign UK deployment serving SDA analysts. All data processed is confirmed Unclassified (ADR-006), so the controls below are aimed at integrity, audit, and operational hygiene rather than at protecting classified material. The security model assumes a trusted operator network in front of nginx, with application-level controls layered behind that.

**SECTION 02**

## Data classification

● **Unclassified.** Confirmed by ADR-006. Applies to UDL TACREP_NOTSOs, elset records, Mattermost content, ClickUp exports, procedure documents, and analyst inputs.
● No handling caveats apply. Commercial cloud providers and commercial AI APIs (Anthropic Claude) are permitted in Phase 2.

When new data sources are added, ADR-006 must be re-evaluated. Any source carrying a higher classification must be rejected at ingest until the system is uplifted.

**SECTION 03**

## Authentication

### Current state

● HS256 JWT bearer tokens issued by `/api/v1/auth/login` and refreshed at `/api/v1/auth/refresh` (ADR-010).
● Access tokens last 30 minutes; refresh tokens last 7 days.
● Passwords hashed with bcrypt via `passlib`.
● Frontend stores both tokens in `localStorage`. Axios injects the access token, refreshes once on 401, and forces logout on refresh failure.
● `get_current_user` validates the token, confirms type is `access`, loads the user, rejects if inactive.

### Bootstrap

There is no public sign-up. The first admin is created with:

```powershell
cd backend
python -m scripts.create_admin --username your.username --password '<choose-something-strong>'
```

Subsequent users are created by administrators. A UI for that is on the backlog.

**SECTION 04**

## Authorisation

Role enum exists on the `User` model (`analyst`, `operator`, `admin`) and a `require_role(*roles)` factory lives in [backend/app/dependencies.py](../../backend/app/dependencies.py). It is not yet used on any route; every authenticated user has the same capabilities at the API surface. Role-based gating lands with the user management slice.

**SECTION 05**

## Audit logging

Every state-changing action writes an audit entry. The audit log is tamper-evident via a SHA-256 hash chain (ADR-008), with concurrent writes serialised by a Postgres advisory lock inside the transaction. Full details in [docs/audit/overview.md](../audit/overview.md).

The `udl.elset.ingest` action type is emitted today. Auth-event action types (`auth.user.login`, `auth.user.logout`, `auth.token.refresh`) are in the taxonomy but not yet emitted; they ship in the next audit-attribution slice.

**SECTION 06**

## Transport security

● TLS terminates at nginx. Self-signed certificate in local development, real certificates in deployed environments.
● TLS is enforced even locally (ADR-004) to prevent posture regressions when moving to deployed environments.
● `UDL_VERIFY_SSL` defaults to `true`. The escape hatch exists for corporate-proxy dev setups; do not disable in deployed environments.
● The internal Docker network `internal` is `driver: bridge` with `internal: true`, so `db` is unreachable from outside the host.

**SECTION 07**

## Secrets management

### Current state

● Local development uses a `.env` file. `.env*` is gitignored except for `.env.example`.
● CI injects environment variables directly (see [.github/workflows/ci.yml](../../.github/workflows/ci.yml)). No real credentials are checked in.
● `APP_SECRET_KEY` signs JWTs. Treat as a credential: do not log it, do not commit it, rotate on suspected compromise (forces all sessions to re-authenticate).
● The `gitleaks` pre-commit hook and CI job scan the repository for accidental secret leaks on every commit and pull request.

### Planned (Phase 2)

● Cloud secret manager (AWS Secrets Manager, Azure Key Vault, or equivalent) replaces `.env` in deployed environments.
● Per-service IAM identities replace the shared `.env` password approach.

**SECTION 08**

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

**SECTION 09**

## Threat surface

| Vector | Mitigation |
|--------|-----------|
| External attacker reaches the application | nginx is the only public endpoint. Backend and DB are on an internal-only Docker network. TLS is enforced. |
| Compromised analyst credentials | Audit log records every action. Hash chain detects retrospective tampering. 30-minute access token expiry limits blast radius. Stolen refresh token valid up to 7 days (revocation backlogged). |
| Compromised UDL credentials | Stored in environment variables, not in source. Phase 2 moves these to a secret manager. Compromise of read-only UDL credentials does not enable writes against our system. |
| SQL injection | SQLAlchemy parameterises every query. No raw string concatenation into SQL. |
| Cross-site scripting (XSS) | React escapes by default. We do not use `dangerouslySetInnerHTML`. |
| Cross-site request forgery (CSRF) | Tokens travel in the `Authorization` header rather than a cookie, removing the standard CSRF vector. |
| Supply-chain compromise | Pinned versions in `requirements.txt` and `package-lock.json`. Dependabot or equivalent is a Phase 2 add. |
| Insider modifies audit log | Application role has INSERT-only permissions on the audit schema. Hash chain detects modifications even by a DBA who bypasses the application. |
| Accidental commit of secrets | gitleaks at pre-commit and in CI. `.env` family in `.gitignore`. |

**SECTION 10**

## Incident response

Phase 1 has no formal incident response runbook. Operational response is owned by the on-call engineer. When `/api/v1/health` returns non-200 or the dashboard is unreachable, follow [docs/runbook/operator-manual.md](../runbook/operator-manual.md).

> **KEY DECISION**
>
> The first hard requirement that turns into a formal incident response runbook is forced sign-out for a compromised refresh token. Today, the mitigation is to rotate `APP_SECRET_KEY`, which invalidates every issued JWT. Plan to land the refresh-token blocklist alongside the IR runbook.

**SECTION 11**

## Review

This document is reviewed when a security-relevant change lands. Triggers include:

● New ingest sources.
● Authentication or authorisation changes.
● Network or infrastructure changes.
● New external integrations (AI APIs, cloud providers).
● Findings from a penetration test or audit.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
