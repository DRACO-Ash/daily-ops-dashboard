#!/bin/sh
# Container entrypoint for the Bluestaq App Store deployment.
#
# 1. Apply alembic migrations, retrying while the PostgreSQL add-on
#    pod finishes starting.
# 2. Optionally bootstrap an admin user from ADMIN_USERNAME and
#    ADMIN_PASSWORD (set them once, then remove them).
# 3. Start uvicorn on $PORT, defaulting to 8080. Plain HTTP; Istio
#    terminates TLS.
set -eu

cd /app

attempts="${MIGRATION_ATTEMPTS:-30}"
i=1
until alembic -c /app/alembic.ini upgrade head; do
    if [ "$i" -ge "$attempts" ]; then
        echo "Migrations failed after $attempts attempts" >&2
        exit 1
    fi
    echo "Database not ready (attempt $i/$attempts), retrying in 5s" >&2
    i=$((i + 1))
    sleep 5
done

if [ -n "${ADMIN_USERNAME:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    # Non-fatal: a sibling replica may create the same user concurrently.
    python -m scripts.create_admin || echo "Admin bootstrap skipped" >&2
fi

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
