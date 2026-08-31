#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_PID=""

cleanup() {
  if [[ -n "$GATEWAY_PID" ]]; then
    kill "$GATEWAY_PID" >/dev/null 2>&1 || true
    wait "$GATEWAY_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

cd -- "$PROJECT_ROOT"
"$PROJECT_ROOT/scripts/python.sh" -m apps.gateway.knowledge_dump_gateway &
GATEWAY_PID="$!"
npm run dev:ui
