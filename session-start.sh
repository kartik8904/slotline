#!/usr/bin/env bash
# Runs at the start of every Claude session (see .claude/settings.json).
# Safe before the project exists: each step only runs once its file is present.
set -u
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0

# Only do heavy setup in Claude cloud sessions, not on your own laptop.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

if [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then
  echo "[session-start] uv sync"
  uv sync >/dev/null 2>&1 || echo "[session-start] uv sync failed; run it manually"
fi

if [ -f compose.yaml ] && command -v docker >/dev/null 2>&1; then
  echo "[session-start] starting postgres, redis, mailpit"
  docker compose up -d postgres redis mailpit >/dev/null 2>&1 \
    || echo "[session-start] docker compose failed; see docs/START-HERE.md section 3"
fi

exit 0
