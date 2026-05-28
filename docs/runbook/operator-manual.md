# Operator Manual

**Classification:** Unclassified
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.1
**Last updated:** 2026-05-27
**Audience:** Operators and on-call engineers responsible for keeping the Daily Operations Dashboard healthy.

## At a glance

The Daily Operations Dashboard runs as four containers behind nginx:

● `nginx` (the only public service)
● `frontend` (Vite-built static assets)
● `backend` (FastAPI, served by uvicorn)
● `db` (PostgreSQL 15)

When something is wrong, the operator's job is to find which of those four is unhappy, fix it, and confirm. This document is the playbook.

## Daily checks

| Check | How | Healthy result |
|-------|-----|---------------|
| Dashboard reachable | Browse to `https://<host>` | Sign-in screen renders |
| Backend health | `curl -k https://<host>/api/v1/health` | `{"status":"ok"}` HTTP 200 |
| Last ingest recent | See "Inspect ingest history" below | An audit row within expected cadence |
| Containers up | `docker compose ps` | All four `Up` |
| Disk space | `df -h` (Linux) or `Get-PSDrive C` (Windows) | Free space above local threshold |

## Starting and stopping

```powershell
cd infra

# Bring everything up
docker compose up -d

# Stop without removing data
docker compose stop

# Tear down (volumes preserved)
docker compose down

# Tear down including the database volume (DESTRUCTIVE)
docker compose down -v
```

## Inspecting logs

```powershell
# Tail the backend
docker compose -f infra/docker-compose.yml logs -f backend

# Last 200 lines from nginx
docker compose -f infra/docker-compose.yml logs --tail 200 nginx

# Database
docker compose -f infra/docker-compose.yml logs db
```

Logs are not persisted outside the container by default. A log-shipping pattern (filebeat or vector to a central sink) is on the Phase 2 backlog.

## Triggering a UDL ingest

The analyst-facing path is the dashboard:

1. Sign in.
2. Navigate to **Element sets**.
3. Set **Epoch since** to the desired lower bound.
4. Optionally set a satellite number or a maximum result count.
5. Click **Pull from UDL**.
6. Wait for the success banner. The table reloads automatically.

The operator-facing path is the API:

```powershell
$body = @{
  epoch_gte = "2026-05-20T00:00:00Z"
  sat_no = 25544
  max_results = 100
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "https://<host>/api/v1/elsets/ingest" `
  -Method POST `
  -Body $body `
  -ContentType "application/json" `
  -SkipCertificateCheck
```

Response shape:

```json
{ "pulled": 17, "inserted": 12, "updated": 5, "skipped": 0 }
```

Once JWT auth lands this endpoint will require a bearer token.

## Inspecting ingest history

The dashboard does not yet surface ingest history. Query the audit log directly:

```powershell
docker compose -f infra/docker-compose.yml exec db psql -U ops_user -d ops_dashboard
```

In `psql`:

```sql
SELECT timestamp, detail::text
  FROM audit.audit_log
 WHERE action_type = 'udl.elset.ingest'
 ORDER BY timestamp DESC
 LIMIT 20;
```

## Database operations

### Open a database shell

```powershell
docker compose -f infra/docker-compose.yml exec db psql -U ops_user -d ops_dashboard
```

### Inspect tables

```sql
\dt public.*
\dt audit.*
\d public.elset
```

### Apply pending migrations

```powershell
alembic upgrade head
```

### Roll back the last migration

```powershell
alembic downgrade -1
```

Only do this if you understand the data impact. Downgrades drop tables.

### Manual integrity check on the audit chain

There is no helper utility yet. To spot-check, walk the chain by `timestamp ASC`, recompute `sha256(previous_hash || canonical_json(payload))`, compare against `entry_hash`. Full mechanics in [docs/audit/overview.md](../audit/overview.md).

## Common failures and fixes

### Symptom: dashboard returns 502 Bad Gateway

Likely cause: nginx is up but the backend is not.

```powershell
docker compose -f infra/docker-compose.yml ps backend
docker compose -f infra/docker-compose.yml logs --tail 200 backend
```

Look for stack traces, missing environment variables, or database connection failures.

### Symptom: `/api/v1/health` returns 500

Likely cause: the backend cannot reach the database.

```powershell
docker compose -f infra/docker-compose.yml ps db
docker compose -f infra/docker-compose.yml logs --tail 200 db
```

If the database is up, check that the backend's `POSTGRES_*` environment variables match the database's actual credentials.

### Symptom: UDL ingest returns HTTP 502 with "UDL rejected credentials"

The `UDL_USERNAME` or `UDL_PASSWORD` is wrong, or has been rotated.

1. Confirm the credential pair with the UDL administrator.
2. Update `.env` (or the cloud secret store in Phase 2).
3. Restart the backend: `docker compose restart backend`.
4. Retry the ingest.

### Symptom: UDL ingest returns HTTP 502 with "UDL request failed"

Network egress to UDL is blocked, or UDL is down.

1. Check connectivity from the backend container:

   ```powershell
   docker compose -f infra/docker-compose.yml exec backend curl -I https://unifieddatalibrary.com
   ```

2. Confirm UDL's status via your usual channel.
3. If a corporate proxy is in the path and TLS verification is failing, the temporary escape hatch is `UDL_VERIFY_SSL=false` in `.env`. Do not leave this off; address the proxy properly.

### Symptom: pre-commit hook keeps rewriting a file

The file has formatting or import-sorting issues that ruff fixes automatically. Re-stage the file and commit again. Do not bypass hooks with `--no-verify`.

### Symptom: alembic complains about an out-of-date head

```powershell
alembic current      # what the database thinks it is on
alembic heads        # what the codebase declares
alembic history      # the chain between them
```

If the database is behind, `alembic upgrade head`. If the codebase is ahead by more than one revision, walk forward with `alembic upgrade +1` to spot any single migration that misbehaves.

## Disaster scenarios

### Database container will not start

1. `docker compose logs db`.
2. If the volume is corrupted, the only path back may be `docker compose down -v` and a restore from backup.
3. Phase 1 has no automated backups. Take this seriously when restoring.

### Audit log integrity in doubt

If a `previous_hash` does not match the prior row's `entry_hash`:

1. Stop further audit writes (stop the backend).
2. Take a database snapshot.
3. Escalate to engineering and to the customer's security point of contact.
4. Do not delete or modify any rows. The chain is forensic evidence.

### Suspected secret leak

If a real credential lands in a commit:

1. Rotate the credential immediately at the source.
2. Force-rewrite history is rarely the right move; treat the credential as already compromised.
3. File an incident note in the team channel.

## See also

● [Architecture overview](../architecture/overview.md)
● [Security overview](../security/overview.md)
● [Audit logging overview](../audit/overview.md)
● [Analyst training manual](../user-handbook/training-manual.md)
