**BLUESTAQ LIMITED** | Developer Setup | **COMMERCIAL IN CONFIDENCE**

# Developer Setup

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.2
**Last updated:** 2026-05-28

> **BLUF**
>
> One-time path from a clean machine to a running dashboard. Python 3.11, Node 20, Docker, a populated `.env`, an admin user created via the bootstrap script, and the test suite green.

**SECTION 01**

## Prerequisites

● **Python 3.11** (3.14 is the longer-term target; 3.11 is what CI runs).
● **Node.js 20** with npm.
● **Docker Desktop** (Windows or macOS) or Docker Engine (Linux), with Docker Compose v2.
● **Git** with line endings configured for your platform. Windows users: the repository works fine with `core.autocrlf=true`.
● **PowerShell 7+** on Windows, or any POSIX shell on macOS or Linux.

**SECTION 02**

## Clone and bootstrap

```powershell
git clone <repo-url> daily-ops-dashboard
cd daily-ops-dashboard
```

**SECTION 03**

## Environment configuration

Copy the example file and fill in real values:

```powershell
Copy-Item .env.example .env
```

Required values:

● `APP_SECRET_KEY` — at least 32 random characters. Generate with:

  ```powershell
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

● `POSTGRES_*` — leave the defaults from `.env.example` for local development.
● `UDL_USERNAME`, `UDL_PASSWORD` — needed only if you want to exercise the UDL ingest path. The application boots without them; ingest fails clearly when invoked.

The `.env` file is gitignored. Do not commit it.

**SECTION 04**

## Python backend

### Virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

### Developer tooling

The pre-commit hooks need a handful of tools that are not in `requirements.txt`:

```powershell
pip install ruff mypy bandit pytest pytest-asyncio pre-commit
pre-commit install
```

**SECTION 05**

## Node frontend

```powershell
cd frontend
npm ci
cd ..
```

**SECTION 06**

## Database and migrations

Bring the database up first:

```powershell
cd infra
docker compose up -d db
cd ..
```

Apply migrations from the project root:

```powershell
alembic upgrade head
```

You can verify with:

```powershell
docker compose -f infra/docker-compose.yml exec db psql -U ops_user -d ops_dashboard -c "\dt"
```

Expected output: the `elset` and `app_user` tables in `public` and `audit_log` in `audit`.

**SECTION 07**

## Bootstrap the first admin

There is no public sign-up. Create the first user via the CLI:

```powershell
cd backend
python -m scripts.create_admin --username your.username --password '<choose-something-strong>'
cd ..
```

The script is idempotent: re-running with the same username updates the password rather than failing.

**SECTION 08**

## Running the application

The simplest path is the full Compose stack:

```powershell
cd infra
docker compose up -d
```

That brings up `db`, `backend`, `frontend`, and `nginx`. The dashboard is then at `https://localhost` (accept the self-signed certificate).

For iterative backend development with auto-reload, run the backend outside Compose:

```powershell
$env:PYTHONPATH = "backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For iterative frontend development with hot module replacement:

```powershell
cd frontend
npm run dev
```

Vite serves on port 5173 and proxies `/api` to `http://backend:8000` (see [frontend/vite.config.ts](../../frontend/vite.config.ts)). For host-side development you may want to change the proxy target to `http://localhost:8000`.

**SECTION 09**

## Tests

### Backend

The backend test suite needs the same environment variables the application needs to boot. Easiest path: keep them in your local `.env` and load that file into the current PowerShell session before running pytest.

```powershell
$env:PYTHONPATH = "backend"
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
    Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim('"').Trim("'")
  }
}
pytest tests/backend
```

The canonical set of variables CI uses lives in [.github/workflows/ci.yml](../../.github/workflows/ci.yml). When you add a new required setting to `Settings`, add it to both `.env.example` and the CI workflow.

### Frontend

```powershell
cd frontend
npm run test
```

vitest is configured with `--passWithNoTests`, so a clean run passes even with no test files.

**SECTION 10**

## Lint and type-check

```powershell
ruff check backend/app
ruff format --check backend/app
mypy backend/app
bandit -r backend/app -ll
```

Or rely on pre-commit:

```powershell
pre-commit run --all-files
```

**SECTION 11**

## Branching and commits

● Trunk: `main`.
● Feature branches: descriptive name, no template enforced yet.
● Conventional Commits: `type(scope): subject`. Existing scopes include `auth`, `elsets`, `backend`, `ci`, `test`, `docs`.
● Pull requests required to land on `main`. CI gates merging.

When the pre-commit hook reformats a file, the commit is aborted. Re-stage the file and commit again. Do not use `--no-verify` to bypass hooks; fix the underlying issue.

**SECTION 12**

## Common operational commands

| Task | Command |
|------|---------|
| Tail backend logs | `docker compose -f infra/docker-compose.yml logs -f backend` |
| Open a database shell | `docker compose -f infra/docker-compose.yml exec db psql -U ops_user -d ops_dashboard` |
| Stop everything | `docker compose -f infra/docker-compose.yml down` |
| Reset database (destructive) | `docker compose -f infra/docker-compose.yml down -v` then `alembic upgrade head` |
| Generate a migration | `alembic revision --autogenerate -m "short message"` |
| Bootstrap an admin user | `cd backend; python -m scripts.create_admin --username <name> --password <secret>` |

**SECTION 13**

## Where to read next

● [Architecture overview](../architecture/overview.md)
● [Architectural decision log](../architecture/decision-log.md)
● [Data model](../architecture/data-model.md)
● [Operator manual](../runbook/operator-manual.md)

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
