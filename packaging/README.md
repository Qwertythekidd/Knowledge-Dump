# Ubuntu packaging

The Debian package embeds the production React bundle in the compiled Tauri
binary, installs immutable application code under `/usr/lib/knowledge-dump`,
and exposes `/usr/bin/knowledge-dump` as both the desktop launcher and the
Codex-storage command-line entry point. It contains no gateway credentials,
Codex authentication, collection data, or development configuration.

Build on Ubuntu 24.04 with the Tauri/WebKitGTK development dependencies:

```bash
sudo apt install build-essential curl file libssl-dev libwebkit2gtk-4.1-dev \
  libappindicator3-dev librsvg2-dev patchelf
npm ci
npm run check
npm run build:deb
```

The build uses the version shared by npm, Tauri, and Cargo and emits:

```text
dist/knowledge-dump_<version>_<architecture>.deb
dist/knowledge-dump_<version>_<architecture>.deb.sha256
```

`build:deb` generates shared-library dependencies from the compiled executable,
normalizes package timestamps from `SOURCE_DATE_EPOCH`, writes package checksums,
and runs structural, desktop-entry, AppStream, and headless CLI validation. Run
validation independently with:

```bash
npm run check:deb -- dist/knowledge-dump_0.1.2_amd64.deb
```

The package never imports development state. A new workstation gets empty XDG
directories and authenticates to a separately deployed Knowledge Dump Gateway.
Gateway tokens are session-only in V1 and are discarded when the application
closes.

## Native Ubuntu acceptance

Copy only the `.deb` and matching `.sha256` file to a clean Ubuntu 24.04 test
workstation. Verify and install through APT so WebKitGTK dependencies resolve:

```bash
cd /path/to/release-directory
sha256sum --check knowledge-dump_0.1.2_amd64.deb.sha256
sudo apt install ./knowledge-dump_0.1.2_amd64.deb
dpkg-query --show --showformat='${Status} ${Version}\n' knowledge-dump
knowledge-dump codex-storage --help
gtk-launch knowledge-dump
```

Confirm that Knowledge Dump appears in the Ubuntu application menu, opens
without the source repository, accepts a configured HTTPS gateway, and creates
state only beneath the current user's XDG directories. Package removal must not
delete user-owned XDG data:

```bash
sudo apt remove knowledge-dump
```

See `docs/iso-integration.md` for the image-builder handoff.
