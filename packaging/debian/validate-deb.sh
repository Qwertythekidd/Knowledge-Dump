#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(node -p "require('$ROOT/package.json').version")"
ARCH="$(dpkg --print-architecture)"
PACKAGE="${1:-$ROOT/dist/knowledge-dump_${VERSION}_${ARCH}.deb}"
EXTRACTED="$(mktemp -d)"
trap 'rm -rf -- "$EXTRACTED"' EXIT

test -f "$PACKAGE"
test "$(dpkg-deb --field "$PACKAGE" Package)" = "knowledge-dump"
test "$(dpkg-deb --field "$PACKAGE" Version)" = "$VERSION"
test "$(dpkg-deb --field "$PACKAGE" Architecture)" = "$ARCH"
dpkg-deb --extract "$PACKAGE" "$EXTRACTED"

test -x "$EXTRACTED/usr/bin/knowledge-dump"
test -x "$EXTRACTED/usr/lib/knowledge-dump/knowledge-dump-desktop"
test -f "$EXTRACTED/usr/share/applications/knowledge-dump.desktop"
test -f "$EXTRACTED/usr/share/metainfo/com.fontainetech.knowledge-dump.metainfo.xml"
test -f "$EXTRACTED/usr/share/icons/hicolor/scalable/apps/knowledge-dump.svg"

"$EXTRACTED/usr/lib/knowledge-dump/knowledge-dump-desktop" codex-storage --help | grep -q restore-default
desktop-file-validate "$EXTRACTED/usr/share/applications/knowledge-dump.desktop"
appstreamcli validate --no-net "$EXTRACTED/usr/share/metainfo/com.fontainetech.knowledge-dump.metainfo.xml"

if find "$EXTRACTED" -type f \( -name '.env' -o -name '.env.*' -o -name '*.map' -o -name 'auth.json' \) -print -quit | grep -q .; then
  printf 'Package contains a forbidden development or credential file.\n' >&2
  exit 1
fi

printf 'Validated %s %s for %s\n' "knowledge-dump" "$VERSION" "$ARCH"
