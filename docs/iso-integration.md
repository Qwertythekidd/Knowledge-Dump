# BookOS ISO integration

Knowledge Dump is delivered to BookOS images as a normal Debian package. The
ISO project must consume a released `.deb`; it must not clone this repository,
install Node.js or Rust, or run a development server on the target workstation.

## Release handoff

The Knowledge Dump release consists of:

```text
knowledge-dump_<version>_amd64.deb
knowledge-dump_<version>_amd64.deb.sha256
```

The ISO build should verify the checksum, add the package to its signed local
APT repository or equivalent package pool, and declare `knowledge-dump` in the
image package manifest. Installing it through APT is required so the generated
GTK, WebKitGTK, and CA-certificate dependencies are resolved by the Ubuntu base
repositories. Do not use a first-boot Git clone or `dpkg -i` without dependency
resolution.

## Filesystem contract

Immutable application files are installed at:

```text
/usr/bin/knowledge-dump
/usr/lib/knowledge-dump/knowledge-dump-desktop
/usr/share/applications/knowledge-dump.desktop
/usr/share/icons/hicolor/scalable/apps/knowledge-dump.svg
/usr/share/metainfo/com.fontainetech.knowledge-dump.metainfo.xml
```

The package creates no home-directory data during image construction. At
runtime each OS user owns their own configuration and state under:

```text
$XDG_CONFIG_HOME/knowledge-dump
$XDG_DATA_HOME/knowledge-dump
$XDG_CACHE_HOME/knowledge-dump
$XDG_STATE_HOME/knowledge-dump
```

Package upgrades replace only immutable files. Package removal and ISO updates
must not erase these user-owned directories.

## Image acceptance gate

Before releasing a BookOS image:

1. Boot the image in a clean VM with networking enabled.
2. Confirm `dpkg-query -W knowledge-dump` reports the intended version.
3. Launch Knowledge Dump from the desktop application menu.
4. Configure and authenticate against a staging Knowledge Dump Gateway.
5. Exercise a small file upload/download and a local Codex collection scan.
6. Reboot and confirm the application still launches and user XDG state remains.
7. Upgrade the package with a newer `.deb` and confirm state is preserved.

Knowledge Dump does not need to start as a system service. It is a per-user
desktop application; the independently deployed gateway remains the server-side
runtime.
