# Ubuntu packaging

The Debian package embeds the production React bundle in the compiled Tauri
binary, installs immutable application code under `/usr/lib/knowledge-dump`,
and exposes `/usr/bin/knowledge-dump` as the desktop launcher.

Build on Ubuntu 24.04 with the Tauri/WebKitGTK development dependencies:

```bash
sudo apt install build-essential curl file libssl-dev libwebkit2gtk-4.1-dev \
  libappindicator3-dev librsvg2-dev patchelf
npm install
bash packaging/debian/build-deb.sh
```

The package never imports development state. A new workstation gets empty XDG
directories and authenticates to a separately deployed Knowledge Dump Gateway.
