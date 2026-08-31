#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$PROJECT_ROOT"

npm run typecheck
npm run build
"$PROJECT_ROOT/scripts/python.sh" -m unittest discover -s apps/gateway/tests -v
"$PROJECT_ROOT/scripts/python.sh" -m compileall -q apps/gateway

printf '%s\n' 'Knowledge Dump checks passed.'
