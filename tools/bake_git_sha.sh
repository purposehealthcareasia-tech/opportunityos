#!/usr/bin/env bash
# Deploy-safe SHA baker. Emits /app/.git-sha with the short SHA at
# build time so the runtime falls through to it when the deployed
# image has no `.git/` directory. Honest "unknown" fallback preserved
# if git rev-parse fails.
#
# Usage in a Dockerfile:
#   COPY tools/bake_git_sha.sh /tmp/bake_git_sha.sh
#   RUN /tmp/bake_git_sha.sh
#
# Usage locally / preview:
#   bash tools/bake_git_sha.sh
set -euo pipefail

cd "$(dirname "$0")/.."

SHA=""
if git rev-parse --short=8 HEAD >/dev/null 2>&1; then
  SHA="$(git rev-parse --short=8 HEAD 2>/dev/null || true)"
fi

if [ -z "$SHA" ]; then
  # HONEST fallback — the runtime handler surfaces this string
  # untouched. Never fabricated.
  SHA="unknown"
fi

echo -n "$SHA" > /app/.git-sha
echo "wrote /app/.git-sha = $SHA"
