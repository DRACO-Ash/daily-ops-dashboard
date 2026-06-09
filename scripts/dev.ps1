<#
.SYNOPSIS
  Local deploy and run for the Daily Operations Dashboard.

.DESCRIPTION
  One file, everything you need:
  - Creates .env from .env.example with a fresh APP_SECRET_KEY (idempotent)
  - Generates a self-signed TLS cert for nginx (idempotent)
  - Brings up the docker compose stack (db, backend, frontend, nginx)
  - Waits for the database to be ready
  - Applies pending alembic migrations
  - Bootstraps the first admin user if app_user is empty
  - Prints the dashboard URL and (by default) tails the backend logs

  Safe to re-run on every check-out.

.PARAMETER Down
  Stop the stack. Database volume preserved.

.PARAMETER Reset
  Stop the stack AND drop the database volume. DESTRUCTIVE.

.PARAMETER Restart
  Stop and start the stack without rebuilding. Useful after a config change.

.PARAMETER NoLogs
  Skip the log tail at the end.

.PARAMETER RegenerateCerts
  Force a fresh self-signed certificate even if one already exists.

.PARAMETER AdminUsername
  Username for the bootstrap admin. Defaults to $env:ADMIN_USERNAME, otherwise prompts.

.PARAMETER AdminPassword
  Password for the bootstrap admin. Defaults to $env:ADMIN_PASSWORD, otherwise prompts.

.EXAMPLE
  .\scripts\dev.ps1
  First-time bootstrap: env, certs, stack, migrations, admin, then tail logs.

.EXAMPLE
  .\scripts\dev.ps1 -NoLogs
  Same as above but does not tail logs at the end.

.EXAMPLE
  $env:ADMIN_USERNAME = "alice"; $env:ADMIN_PASSWORD = "s3cret"; .\scripts\dev.ps1 -NoLogs

.EXAMPLE
  .\scripts\dev.ps1 -Down
  Stop the stack. Database preserved.

.EXAMPLE
  .\scripts\dev.ps1 -Reset
  Stop the stack and drop the database volume. Destructive.
#>

[CmdletBinding()]
param(
    [switch]$Down,
    [switch]$Reset,
    [switch]$Restart,
    [switch]$NoLogs,
    [switch]$RegenerateCerts,
    [string]$AdminUsername = $env:ADMIN_USERNAME,
    [string]$AdminPassword = $env:ADMIN_PASSWORD
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Paths -----------------------------------------------------------
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $RepoRoot "infra\docker-compose.yml"
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"
$CertsDir = Join-Path $RepoRoot "infra\certs"
$CertFile = Join-Path $CertsDir "cert.pem"
$KeyFile = Join-Path $CertsDir "key.pem"

# Output helpers --------------------------------------------------
function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
    Write-Host "    OK $msg" -ForegroundColor Green
}
function Write-Note([string]$msg) {
    Write-Host "       $msg" -ForegroundColor Gray
}
function Write-Warn([string]$msg) {
    Write-Host "    !! $msg" -ForegroundColor Yellow
}
function Write-Fail([string]$msg) {
    Write-Host "    XX $msg" -ForegroundColor Red
}

function Invoke-Required {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$ErrorMessage
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        $msg = if ($ErrorMessage) { $ErrorMessage } else { "$Command $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
        throw $msg
    }
}

# Pre-flight ------------------------------------------------------
function Assert-Docker {
    try {
        docker info *> $null
        if ($LASTEXITCODE -ne 0) { throw "docker info exited non-zero" }
    } catch {
        Write-Fail "Docker is not running. Start Docker Desktop and re-run this script."
        return $false
    }
    return $true
}

# Environment -----------------------------------------------------
function New-AppSecret {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Ensure-Env {
    Write-Step "Environment file"
    if (Test-Path $EnvFile) {
        Write-Ok ".env already exists"
        return
    }
    if (-not (Test-Path $EnvExample)) {
        throw ".env.example not found at $EnvExample"
    }
    Copy-Item $EnvExample $EnvFile
    $secret = New-AppSecret
    (Get-Content $EnvFile) -replace '^APP_SECRET_KEY=.*$', "APP_SECRET_KEY=$secret" |
        Set-Content $EnvFile
    Write-Ok ".env created from .env.example"
    Write-Note "APP_SECRET_KEY set to a fresh random value."
    Write-Note "Edit $EnvFile to add UDL_USERNAME and UDL_PASSWORD before triggering ingests."
}

# TLS certificate -------------------------------------------------
function Ensure-Certs {
    Write-Step "TLS certificate"
    if ((Test-Path $CertFile) -and (Test-Path $KeyFile) -and (-not $RegenerateCerts)) {
        Write-Ok "Self-signed certificate already present"
        return
    }
    if (-not (Test-Path $CertsDir)) {
        New-Item -ItemType Directory -Path $CertsDir | Out-Null
    }
    Write-Note "Generating a self-signed certificate via docker (alpine + openssl)..."
    $certsMount = $CertsDir.Replace('\', '/')
    $sh = "apk add --no-cache openssl >/dev/null 2>&1 && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem -subj '/CN=localhost'"
    docker run --rm -v "${certsMount}:/certs" -w /certs alpine sh -c $sh
    if ($LASTEXITCODE -ne 0) {
        throw "openssl cert generation failed"
    }
    Write-Ok "cert.pem and key.pem written to infra\certs\"
    Write-Note "Your browser will warn about the self-signed cert; that is expected for local dev."
}

# Compose ---------------------------------------------------------
function Get-ComposeBase {
    # `--env-file` is required because Compose otherwise looks for `.env`
    # in the directory of the compose file (infra/), where it does not
    # exist. The repo-root .env holds POSTGRES_PASSWORD and friends.
    $base = @("compose", "-f", $ComposeFile)
    if (Test-Path $EnvFile) {
        $base += @("--env-file", $EnvFile)
    }
    return $base
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    Invoke-Required -Command "docker" -Arguments ((Get-ComposeBase) + $ComposeArgs)
}

function Down-Stack {
    param([switch]$WithVolumes)
    Write-Step "Stopping the stack"
    if ($WithVolumes) {
        Invoke-Compose @("down", "-v")
        Write-Ok "Stack down. Database volume removed."
    } else {
        Invoke-Compose @("down")
        Write-Ok "Stack down. Volumes preserved."
    }
}

function Start-Stack {
    Write-Step "Bringing up the stack"
    Invoke-Compose @("up", "-d", "--build")
    Write-Ok "Containers started"
}

# Database --------------------------------------------------------
function Wait-DbReady {
    Write-Step "Waiting for the database"
    $base = Get-ComposeBase
    $probeArgs = $base + @("exec", "-T", "db", "pg_isready", "-U", "ops_user", "-d", "ops_dashboard")
    $maxTries = 60
    for ($i = 0; $i -lt $maxTries; $i++) {
        & docker @probeArgs *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Database is ready"
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Database failed to become ready after $maxTries seconds. Check 'docker compose logs db'."
}

function Apply-Migrations {
    Write-Step "Applying alembic migrations"
    Invoke-Compose @("exec", "-T", "-w", "/workspace", "backend", "alembic", "upgrade", "head")
    Write-Ok "Migrations applied (at head)"
}

# Admin bootstrap -------------------------------------------------
function Test-AdminExists {
    $base = Get-ComposeBase
    $queryArgs = $base + @(
        "exec", "-T", "db",
        "psql", "-U", "ops_user", "-d", "ops_dashboard",
        "-tA", "-c", "SELECT COUNT(*) FROM app_user"
    )
    $count = & docker @queryArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    return ([int]$count.Trim()) -gt 0
}

function Read-SecurePassword {
    $secure = Read-Host "    Admin password (input hidden)" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Bootstrap-Admin {
    Write-Step "Bootstrapping admin user"
    if (Test-AdminExists) {
        Write-Ok "app_user already has at least one row; bootstrap skipped"
        return
    }
    $username = $AdminUsername
    $password = $AdminPassword
    if (-not $username) {
        $username = Read-Host "    Admin username"
    }
    if (-not $password) {
        $password = Read-SecurePassword
    }
    if ([string]::IsNullOrWhiteSpace($username) -or [string]::IsNullOrWhiteSpace($password)) {
        throw "Username and password are required"
    }
    Invoke-Compose @(
        "exec", "-T", "backend",
        "python", "-m", "scripts.create_admin",
        "--username", $username,
        "--password", $password
    )
    Write-Ok "Admin user '$username' created"
}

# Output ----------------------------------------------------------
function Show-Banner {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    Write-Host "  Daily Operations Dashboard" -ForegroundColor White
    Write-Host "  https://localhost  (accept the self-signed certificate)" -ForegroundColor White
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    Write-Host ""
}

function Tail-Logs {
    Write-Step "Tailing backend logs (Ctrl-C to stop)"
    Invoke-Compose @("logs", "-f", "backend")
}

# Main ------------------------------------------------------------
if (-not (Assert-Docker)) { exit 1 }

if ($Reset) {
    Down-Stack -WithVolumes
    exit 0
}

if ($Down) {
    Down-Stack
    exit 0
}

if ($Restart) {
    Down-Stack
}

Ensure-Env
Ensure-Certs
Start-Stack
Wait-DbReady
Apply-Migrations
Bootstrap-Admin
Show-Banner

if (-not $NoLogs) {
    Tail-Logs
}
