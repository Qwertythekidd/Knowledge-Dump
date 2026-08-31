# Development

## Repository layout

```text
apps/desktop-ui       React/Vite development interface
apps/desktop-native   Tauri/WebKitGTK Ubuntu shell
apps/gateway          Mock gateway and future production API boundary
packages/protocol     Shared browser/gateway contract types
infra/spaces          DigitalOcean Spaces operational contract
packaging/debian      Native package scaffold
```

## Local loop

`npm run dev` starts the mock gateway on `127.0.0.1:8787` and Vite on
`127.0.0.1:5173`. Vite proxies `/api` to the gateway, avoiding development CORS
configuration and keeping browser calls aligned with the production API path.

The gateway persists its mock catalog under the XDG data root. To run a clean
isolated instance without changing your normal user state:

```bash
KNOWLEDGE_DUMP_DATA_HOME=/tmp/knowledge-dump-dev-data npm run dev
```

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

## Mock limitations

The mock does not upload source file bytes. It records selected file metadata,
simulates transfer progress in the UI, and returns generated placeholder
downloads. PostgreSQL, password hashing, email verification, object encryption,
presigned multipart transfers, version reconciliation, and system keyring
storage are production phases behind the same interfaces.
