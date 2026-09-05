#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ROOT"

exec cargo run --quiet --manifest-path apps/desktop-native/Cargo.toml -- codex-storage "$@"
