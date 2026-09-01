# Development

## Repository layout

```text
apps/desktop-ui       React/Vite development interface
apps/desktop-native   Tauri/WebKitGTK Ubuntu shell
apps/gateway          Account, catalog, device, and session gateway
packages/protocol     Shared browser/gateway contract types
infra/spaces          DigitalOcean Spaces operational contract
packaging/debian      Native package scaffold
```

## Local loop

Run `bash scripts/setup-dev.sh` once. Then `npm run dev` starts the gateway on
`127.0.0.1:8787` and Vite on
`127.0.0.1:5173`. Vite proxies `/api` to the gateway, avoiding development CORS
configuration and keeping browser calls aligned with the production API path.

The gateway persists its development catalog under the XDG data root. To run a clean
isolated instance without changing your normal user state:

```bash
KNOWLEDGE_DUMP_DATA_HOME=/tmp/knowledge-dump-dev-data npm run dev
```

Parallel checkouts can override `KNOWLEDGE_DUMP_GATEWAY_PORT`,
`KNOWLEDGE_DUMP_GATEWAY_DEV_URL`, and `VITE_DEV_PORT` to avoid port collisions.

## Native loop

Install the Ubuntu WebKitGTK and Tauri build dependencies, build the UI, then
run the native shell:

```bash
npm run build
cd apps/desktop-native
cargo run
```

The shell currently loads the Vite development URL when
`KNOWLEDGE_DUMP_DESKTOP_URL` is set. Bundled production assets are configured in
`tauri.conf.json`.

## Current limitations

The development storage adapter writes real multipart bytes beneath the XDG
data root. It exercises part grants, ETag checkpoints, resume, provider
verification, range downloads, abort, and purge without requiring a DigitalOcean
account. DigitalOcean Spaces uses the same API with direct presigned transfers.

Content encryption, conflict resolution, and system-keyring storage remain
later work. Do not use the current build for secrets or sensitive production
data.
