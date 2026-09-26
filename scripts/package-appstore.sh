#!/bin/sh
# Build the Bluestaq App Store upload package from the committed tree.
#
#   ./scripts/package-appstore.sh            -> dist/daily-ops-dashboard-<version>.zip
#
# Uses `git archive`, so only tracked files at HEAD are included (no
# .env, node_modules or build output). Local-dev tooling, CI config and
# non-source documents are excluded; the root Dockerfile is the single
# build entrypoint on the platform.
set -eu

cd "$(git rev-parse --show-toplevel)"

version="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' backend/app/api/v1/routes/health.py)"
name="daily-ops-dashboard"
out="dist/${name}-${version}.zip"

if [ -n "$(git status --porcelain)" ]; then
    echo "Warning: uncommitted changes are NOT included in the package." >&2
fi

mkdir -p dist
rm -f "$out"

git archive --format=zip --output="$out" HEAD -- . \
    ':(exclude).github' \
    ':(exclude).pre-commit-config.yaml' \
    ':(exclude)infra' \
    ':(exclude)scripts/dev.ps1' \
    ':(exclude)backend/Dockerfile' \
    ':(exclude)frontend/Dockerfile' \
    ':(exclude)*.xlsx' \
    ':(exclude)*.docx' \
    ':(exclude)README_CLASSIFICATION.txt'

echo "Wrote $out ($(du -h "$out" | cut -f1))"
