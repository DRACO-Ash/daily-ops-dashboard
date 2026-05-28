**BLUESTAQ LIMITED** | Audit Logging Overview | **COMMERCIAL IN CONFIDENCE**

# Audit Logging Overview

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **STRATEGIC SIGNIFICANCE**
>
> Every state-changing action is recorded in a tamper-evident chain. Any retrospective edit, whether through the application, the database, or direct disk access, is detectable by recomputing the hash chain. The audit log is the load-bearing trust artefact for the whole system.

**SECTION 01**

## Intent

Every state-changing action in the Daily Operations Dashboard is recorded in a tamper-evident audit trail. The trail can be replayed end-to-end by an investigator, and any retrospective edit is detectable by recomputing the hash chain.

**SECTION 02**

## Schema isolation

The audit log lives in its own PostgreSQL schema (ADR-005).

● Schema: `audit`
● Table: `audit.audit_log`
● Application role permissions: `INSERT` only.

The application cannot UPDATE, DELETE, or TRUNCATE audit rows. A privileged DBA can still bypass these permissions, but the hash chain detects any modification after the fact.

**SECTION 03**

## Hash chain mechanism

Each row carries two hash columns:

● `previous_hash` is the `entry_hash` of the immediately prior row, or NULL for the first row.
● `entry_hash` is `sha256(previous_hash + canonical_json(payload))`, hex-encoded.

The `payload` is a canonical JSON serialisation of:

```json
{
  "action_type":  "...",
  "entity_type":  "...",
  "entity_id":    "...",
  "user_id":      "...",
  "ip_address":   "...",
  "detail":       { ... },
  "timestamp":    "..."
}
```

Canonicalisation rules used by [backend/app/services/audit.py](../../backend/app/services/audit.py):

● `json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)`.
● Keys are alphabetically ordered.
● No whitespace.
● Non-JSON-serialisable values (UUIDs, datetimes) fall back to `str()`.

To verify the chain, walk the table by `timestamp ASC`, recompute each `entry_hash`, and assert equality. Any mismatch points to either a tampered row or a row missing from the chain.

**SECTION 04**

## Concurrency control

If two ingests fire at the same moment, both would naively read the same `previous_hash` and create two rows that both claim it as their predecessor, forking the chain. The audit writer prevents this with a Postgres advisory lock taken inside the transaction (ADR-008):

```python
await db.execute(
    text("SELECT pg_advisory_xact_lock(:k)"),
    {"k": AUDIT_ADVISORY_LOCK_KEY},
)
```

`pg_advisory_xact_lock` releases automatically when the transaction commits or rolls back, so the lock duration is bounded by the audit write itself.

The advisory key (`0x4F505841` in [backend/app/services/audit.py](../../backend/app/services/audit.py)) is constant across the whole application. Other features that need to coordinate independently must use a different key.

**SECTION 05**

## Action type taxonomy

Action types are dotted strings. The convention is `<domain>.<entity>.<verb>`. Current and planned values:

| Action type | Description | Status |
|-------------|-------------|--------|
| `udl.elset.ingest` | UDL element-set ingest run completed. `detail` carries the request and the pulled/inserted/updated/skipped counts. | Active |
| `udl.notso.ingest` | UDL Notice to Space Operators ingest run completed. `detail` carries the request (`effective_from_gte`, `msg_type`, `max_results`) and the same counts as elset ingest. | Active |
| `udl.tacrep.ingest` | UDL Tactical Report ingest run. | Planned |
| `auth.user.login` | Login attempt. `detail.success` is true for successful login; false with `detail.reason` set to `unknown_user`, `inactive_user`, or `wrong_password` for failures. `user_id` is NULL only for `unknown_user`. | Active |
| `auth.user.logout` | Logout attempt via `POST /auth/logout` (refresh token in body). `detail.success` true for success; false with `detail.reason` set to `invalid_token`, `missing_claim`, `malformed_subject`, or `already_revoked` for failures. | Active |
| `auth.token.refresh` | Refresh-token exchange. `detail.success` true for success; false with `detail.reason` set to `invalid_token`, `missing_subject`, `missing_jti`, `malformed_subject`, `revoked_token`, or `inactive_user` for failures. On success the old refresh-token JTI is added to the `revoked_jti` block-list. | Active |
| `procedure.doc.upload` | Procedure document uploaded. | Planned |
| `analyst.note.create` | Analyst created a note. | Planned |

New action types should be added to this table when introduced.

**SECTION 06**

## What gets recorded

For every audit row:

● **`action_type`** — see the taxonomy above.
● **`entity_type`** and **`entity_id`** — what the action acted on. For ingest runs, `entity_type = "elset_ingest_run"` and `entity_id` is unset (the action is bulk).
● **`user_id`** — the authenticated user, populated from the JWT subject (ADR-010). NULL only for actions performed outside an authenticated route (for example, scheduled background ingest once implemented).
● **`ip_address`** — the originating IP, populated from `request.client.host` when available.
● **`detail`** — JSON-serialised payload with action-specific fields. For ingest runs, this includes the request parameters and the result counts.

**SECTION 07**

## Reading the audit log

### Through the dashboard (operator + admin)

`GET /api/v1/audit` returns paginated audit rows. Role-gated to `operator` and `admin`; analysts receive HTTP 403. Query parameters: `action_type`, `user_id`, `since`, `until`, `limit`, `offset`. The dashboard's **Audit log** page (visible in the side nav for the relevant roles) wraps this endpoint with a filter form and a pagination control.

### Direct database access (investigators)

To inspect from the database:

```sql
SELECT timestamp, action_type, entity_type, detail::text
  FROM audit.audit_log
 ORDER BY timestamp DESC
 LIMIT 100;
```

To verify integrity (manual approach until a verification utility lands):

```sql
SELECT id, timestamp, previous_hash, entry_hash, detail
  FROM audit.audit_log
 ORDER BY timestamp ASC;
```

Then for each row, recompute `sha256(previous_hash || canonical_json(payload))` and compare against `entry_hash`. A verification utility is in the backlog.

**SECTION 08**

## Exports

Audit exports for compliance review land in `audit/` at the project root (gitignored). The export utility is in the backlog. Once it ships, exports will be CSV or JSON, marked with the export timestamp and the operator who triggered it. The export itself is audit-logged with action type `audit.export.run`.

**SECTION 09**

## Backups

Audit data is included in standard PostgreSQL backups. Backup frequency and retention are environment-specific; see the deployment-environment runbook for the relevant target.

**SECTION 10**

## Open items

● No verification utility exists yet. Investigators must currently recompute hashes manually.
● Audit retention policy (how long to keep audit rows before archiving) is undecided. Default behaviour is to keep everything forever.
● The audit viewer is read-only. A "verify the chain" button that runs the integrity check from the UI is on the backlog.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
