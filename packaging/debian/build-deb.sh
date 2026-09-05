#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_VERSION="$(node -p "require('$ROOT/package.json').version")"
VERSION="${KNOWLEDGE_DUMP_VERSION:-$PROJECT_VERSION}"
ARCH="${KNOWLEDGE_DUMP_ARCH:-$(dpkg --print-architecture)}"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct)}"
export SOURCE_DATE_EPOCH
STAGE="$ROOT/dist/deb/knowledge-dump_${VERSION}_${ARCH}"
OUTPUT="$ROOT/dist/knowledge-dump_${VERSION}_${ARCH}.deb"
SHLIB_WORK="$(mktemp -d)"
trap 'rm -rf -- "$SHLIB_WORK"' EXIT

if [[ "$VERSION" != "$PROJECT_VERSION" ]]; then
  printf 'Version mismatch: package.json is %s but requested Debian version is %s\n' "$PROJECT_VERSION" "$VERSION" >&2
  exit 1
fi
for VERSION_FILE in \
  "$(node -p "require('$ROOT/apps/desktop-ui/package.json').version")" \
  "$(node -p "require('$ROOT/packages/protocol/package.json').version")" \
  "$(node -p "require('$ROOT/apps/desktop-native/tauri.conf.json').version")" \
  "$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/apps/desktop-native/Cargo.toml" | head -n 1)"; do
  if [[ "$VERSION_FILE" != "$VERSION" ]]; then
    printf 'Application version metadata is not synchronized with %s.\n' "$VERSION" >&2
    exit 1
  fi
done
if [[ ! "$VERSION" =~ ^[0-9][0-9A-Za-z.+:~-]*$ ]]; then
  printf 'Invalid Debian package version: %s\n' "$VERSION" >&2
  exit 1
fi

cd -- "$ROOT"
npm run build --workspace @knowledge-dump/protocol
(
  cd -- apps/desktop-native
  "$ROOT/node_modules/.bin/tauri" build --ci --no-bundle
)

rm -rf -- "$STAGE"
install -Dm755 apps/desktop-native/target/release/knowledge-dump-desktop "$STAGE/usr/lib/knowledge-dump/knowledge-dump-desktop"
install -Dm755 packaging/debian/launcher.sh "$STAGE/usr/bin/knowledge-dump"
install -Dm644 packaging/debian/knowledge-dump.desktop "$STAGE/usr/share/applications/knowledge-dump.desktop"
install -Dm644 packaging/debian/com.fontainetech.knowledge-dump.metainfo.xml "$STAGE/usr/share/metainfo/com.fontainetech.knowledge-dump.metainfo.xml"
install -Dm644 packaging/icons/knowledge-dump.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/knowledge-dump.svg"
install -Dm644 README.md "$STAGE/usr/share/doc/knowledge-dump/README.md"
install -Dm644 docs/codex-storage.md "$STAGE/usr/share/doc/knowledge-dump/codex-storage.md"
install -Dm644 packaging/debian/copyright "$STAGE/usr/share/doc/knowledge-dump/copyright"
gzip -9n -c packaging/debian/changelog > "$STAGE/usr/share/doc/knowledge-dump/changelog.gz"
chmod 0644 "$STAGE/usr/share/doc/knowledge-dump/changelog.gz"
install -d -m755 "$STAGE/usr/share/man/man1"
gzip -9n -c packaging/debian/knowledge-dump.1 > "$STAGE/usr/share/man/man1/knowledge-dump.1.gz"
chmod 0644 "$STAGE/usr/share/man/man1/knowledge-dump.1.gz"

mkdir -p -- "$SHLIB_WORK/debian" "$STAGE/DEBIAN"
install -Dm644 packaging/debian/shlibdeps-control "$SHLIB_WORK/debian/control"
SHLIB_DEPS="$(cd -- "$SHLIB_WORK" && dpkg-shlibdeps -O "$STAGE/usr/lib/knowledge-dump/knowledge-dump-desktop" | sed -n 's/^shlibs:Depends=//p')"
INSTALLED_SIZE="$(du -sk "$STAGE/usr" | cut -f1)"
sed \
  -e "s/@VERSION@/$VERSION/g" \
  -e "s/@ARCH@/$ARCH/g" \
  -e "s/@INSTALLED_SIZE@/$INSTALLED_SIZE/g" \
  -e "s/@SHLIB_DEPS@/$SHLIB_DEPS, ca-certificates/g" \
  packaging/debian/control.in > "$STAGE/DEBIAN/control"

(
  cd -- "$STAGE"
  find usr -type f -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums
)
find "$STAGE" -print0 | xargs -0 touch --no-dereference --date="@$SOURCE_DATE_EPOCH"

dpkg-deb --build --root-owner-group -Zxz -z9 "$STAGE" "$OUTPUT"
(
  cd -- "$ROOT/dist"
  sha256sum "$(basename -- "$OUTPUT")" > "$(basename -- "$OUTPUT").sha256"
)
bash packaging/debian/validate-deb.sh "$OUTPUT"
printf 'Built %s\n' "$OUTPUT"
printf 'Checksum %s.sha256\n' "$OUTPUT"
