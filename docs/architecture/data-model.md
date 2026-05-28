**BLUESTAQ LIMITED** | Data Model | **COMMERCIAL IN CONFIDENCE**

# Data Model

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **BLUF**
>
> Two PostgreSQL schemas. `public` holds operational data (`elset`, `app_user` today; NOTSO, TACREP, Mattermost, and procedure documents on the roadmap). `audit` holds an append-only, hash-chained audit trail with INSERT-only application permissions.

**SECTION 01**

## Schemas

PostgreSQL hosts two schemas:

● `public` — operational data the application reads and writes.
● `audit` — append-only audit log. The application role has INSERT-only permissions (see ADR-005).

**SECTION 02**

## Tables in `public`

### `elset`

Stores UDL element sets ingested via the manual trigger or, in a later slice, by scheduled pull.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | UUID | no | Primary key. Generated client-side via `uuid.uuid4`. |
| `udl_id` | varchar(64) | yes | UDL's own identifier. Unique when present. Natural key for dedupe. |
| `sat_no` | integer | no | NORAD catalogue number. Indexed. |
| `epoch` | timestamptz | no | Element-set epoch in UTC. Indexed. |
| `mean_motion` | double precision | yes | Revolutions per day. |
| `eccentricity` | double precision | yes | Orbit eccentricity (0-1). |
| `inclination` | double precision | yes | Degrees. |
| `raan` | double precision | yes | Right ascension of ascending node, degrees. |
| `arg_of_perigee` | double precision | yes | Argument of perigee, degrees. |
| `mean_anomaly` | double precision | yes | Degrees. |
| `rev_no` | integer | yes | Revolution number at epoch. |
| `bstar` | double precision | yes | Atmospheric drag coefficient. |
| `mean_motion_dot` | double precision | yes | First derivative of mean motion. |
| `mean_motion_ddot` | double precision | yes | Second derivative of mean motion. |
| `semi_major_axis` | double precision | yes | Kilometres. |
| `period` | double precision | yes | Orbital period, minutes. |
| `apogee` | double precision | yes | Kilometres above Earth surface. |
| `perigee` | double precision | yes | Kilometres above Earth surface. |
| `line1` | varchar(70) | yes | Raw TLE line 1. |
| `line2` | varchar(70) | yes | Raw TLE line 2. |
| `classification_marking` | varchar(50) | yes | UDL classification (typically `U` for Unclassified). |
| `data_mode` | varchar(20) | yes | UDL data mode (`REAL`, `TEST`, `SIMULATED`, `EXERCISE`). |
| `source` | varchar(100) | yes | UDL source identifier (for example `18 SPCS`). |
| `raw` | jsonb | no | Full UDL payload preserved verbatim. |
| `created_at` | timestamptz | no | Row creation timestamp. |
| `updated_at` | timestamptz | no | Row last-update timestamp, refreshed on upsert. |

**Indexes**

● `uq_elset_udl_id` — unique index on `udl_id`. Enables `INSERT ... ON CONFLICT (constraint=uq_elset_udl_id)` upsert.
● `ix_elset_sat_no` — single-column index for per-satellite queries.
● `ix_elset_epoch` — single-column index for time-range queries.
● `ix_elset_sat_no_epoch` — composite index for the common "this object's recent history" query.

> **NOTE**
>
> The raw payload is preserved in `raw` so that UDL schema additions are never lost on the way in. Typed columns mirror the fields analysts actually query against. See ADR-007 for the design rationale.

### `app_user`

Authenticated users of the dashboard. Created by the bootstrap script or future admin UI.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | UUID | no | Primary key. |
| `username` | varchar(50) | no | Unique, lowercase. Indexed. |
| `email` | varchar(255) | yes | Unique when present. |
| `password_hash` | varchar(255) | no | bcrypt hash via `passlib`. |
| `role` | varchar(20) | no | One of `analyst`, `operator`, `admin`. |
| `is_active` | boolean | no | Deactivated users cannot sign in. |
| `created_at` | timestamptz | no | Server-set. |
| `updated_at` | timestamptz | no | Server-set on update. |

**Indexes**

● `uq_app_user_username` — unique index on `username`.
● `uq_app_user_email` — unique index on `email` when present.
● `ix_app_user_username` — query index.

### `revoked_jti`

Block-list of revoked JWT IDs. Populated on every logout and on every refresh-token rotation. Used by `/auth/refresh` and `/auth/logout` to reject re-use of a revoked token.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `jti` | varchar(64) | no | The token's `jti` claim. Primary key. |
| `user_id` | UUID | yes | The token's subject. Indexed. Nullable for revocations where the subject could not be decoded. |
| `revoked_at` | timestamptz | no | When the revocation was recorded. |
| `expires_at` | timestamptz | no | When the underlying token would have expired naturally. Rows past this point are safe to prune. Indexed. |

**Indexes**

● `ix_revoked_jti_user_id` — supports per-user revocation queries.
● `ix_revoked_jti_expires_at` — supports the pruning job (backlogged).

**SECTION 03**

## Tables in `audit`

### `audit.audit_log`

Append-only audit trail. The application role has INSERT only; no UPDATE, DELETE, or TRUNCATE.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | UUID | no | Primary key. |
| `timestamp` | timestamptz | no | Server-side default `now()`. |
| `user_id` | UUID | yes | The authenticated user, when one is in scope. |
| `action_type` | varchar(100) | no | Dotted action identifier, for example `udl.elset.ingest`. |
| `entity_type` | varchar(100) | yes | The kind of thing the action acted on. |
| `entity_id` | varchar(255) | yes | The identifier of that thing. |
| `ip_address` | varchar(45) | yes | IPv4 or IPv6. |
| `detail` | text | yes | JSON-serialised payload with action-specific fields. |
| `previous_hash` | varchar(64) | yes | `entry_hash` of the prior row, or NULL for the first row. |
| `entry_hash` | varchar(64) | no | `sha256(previous_hash + serialised_payload)`. |

The hash chain and the advisory-lock concurrency control are described in [docs/audit/overview.md](../audit/overview.md).

**SECTION 04**

## Migrations

All schema changes are managed by Alembic.

● [alembic.ini](../../alembic.ini) — repo-root configuration. `script_location = migrations`, `prepend_sys_path = backend`.
● [migrations/env.py](../../migrations/env.py) — async-aware. Imports all model modules so autogenerate sees them. Pulls the database URL from `app.config.settings.database_url`.
● [migrations/versions/](../../migrations/versions/) — one file per migration.

To apply migrations:

```powershell
alembic upgrade head
```

To produce a new autogenerated migration after changing a model:

```powershell
alembic revision --autogenerate -m "short message"
```

Hand-crafted migrations are preferred for the first migration of a new feature (see ADR-007). Autogenerated migrations are fine for incremental column additions.

**SECTION 05**

## Future tables

Planned for follow-on slices:

● `notso` — Notice to Space Operators.
● `tacrep` — Tactical Reports.
● `mattermost_message` — bot-collected operational chat.
● `procedure_doc` — uploaded analyst procedure documents.

Each new feature should follow the `elset` pattern: typed columns for queryable fields, a `raw` JSONB column for the source payload (where the source has one), and an audit entry on every state change.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
