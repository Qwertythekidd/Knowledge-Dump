#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${KNOWLEDGE_DUMP_VERSION:-0.1.0}"
ARCH="${KNOWLEDGE_DUMP_ARCH:-amd64}"
STAGE="$ROOT/dist/deb/knowledge-dump_${VERSION}_${ARCH}"
OUTPUT="$ROOT/dist/knowledge-dump_${VERSION}_${ARCH}.deb"

cd -- "$ROOT"
npm run build
cargo build --manifest-path apps/desktop-native/Cargo.toml --release

rm -rf -- "$STAGE"
install -Dm755 apps/desktop-native/target/release/knowledge-dump-desktop "$STAGE/usr/lib/knowledge-dump/knowledge-dump-desktop"
install -Dm755 packaging/debian/launcher.sh "$STAGE/usr/bin/knowledge-dump"
install -Dm644 packaging/debian/knowledge-dump.desktop "$STAGE/usr/share/applications/knowledge-dump.desktop"
install -Dm644 packaging/icons/knowledge-dump.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/knowledge-dump.svg"
install -Dm644 README.md "$STAGE/usr/share/doc/knowledge-dump/README.md"

mkdir -p -- "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: knowledge-dump
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: libwebkit2gtk-4.1-0, libgtk-3-0, libsoup-3.0-0
Maintainer: Fontaine Tech <support@fontainetech.ai>
Description: Native private cloud workspace for Ubuntu
 Knowledge Dump provides an account-scoped file library backed by an
 independently deployed gateway and S3-compatible object storage.
CONTROL

dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT"
printf 'Built %s\n' "$OUTPUT"
