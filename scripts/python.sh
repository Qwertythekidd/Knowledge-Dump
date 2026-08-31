#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${KNOWLEDGE_DUMP_PYTHON:-}" ]]; then
  exec "$KNOWLEDGE_DUMP_PYTHON" "$@"
fi
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" "$@"
fi
exec python3 "$@"
