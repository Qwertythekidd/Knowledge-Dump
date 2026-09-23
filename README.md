# Knowledge Dump

Knowledge Dump is a standalone Ubuntu-native cloud file manager. It provides a
desktop workspace for organizing, uploading, downloading, and recovering files
through an independently deployed Knowledge Dump Gateway.

The repository intentionally does not depend on BookOS or its gateway.

## Version 0.1.3

The current foundation includes:

- a React desktop interface with authentication, file management, transfers,
  storage health, and settings surfaces;
- a PostgreSQL/SQLite account and catalog gateway with secure rotating sessions;
- shared TypeScript protocol definitions;
- a Tauri/WebKitGTK native shell scaffold;
- a plain, refreshable local Codex workspace collection with manifest
  verification, isolated restore testing, and guarded fresh-workstation restore;
- resumable multipart uploads and short-lived DigitalOcean Spaces transfers;
- Debian packaging and XDG filesystem documentation.

The gateway stores account-scoped, versioned metadata and verifies object bytes
before catalog commit. Local development uses a disk-backed multipart adapter;
production uses short-lived presigned requests against a private Space.

## Quick start

Requirements: Node.js 20+, npm, Python 3.10+, and Python venv support.

```bash
bash scripts/setup-dev.sh
npm run dev
```

Open `http://127.0.0.1:5173` and sign in with:

```text
Email: demo@knowledge-dump.local
Password: knowledge-dump
```

Run verification with:

```bash
npm run check
```

Build and validate the production Ubuntu package with:

```bash
npm run build:deb
```

The resulting `.deb` is a self-contained native desktop release and does not
require this repository, Node.js, Rust, Python, or a development server on the
installed workstation. See [Ubuntu packaging](packaging/README.md) and
[BookOS ISO integration](docs/iso-integration.md).

Discover and update the local Codex structured collection with:

```bash
npm run codex:storage -- discover
npm run codex:storage -- collect
```

The browser development loop uses the real React client against the account and
catalog gateway on an XDG-backed SQLite database. The same schema supports
PostgreSQL deployments. `npm run dev:native` opens the client in WebKitGTK after
the gateway is running. Uploads transfer real bytes and can resume completed
multipart checkpoints. Client-side encryption remains phase 4 work, so
sensitive archives and secrets must not be uploaded yet.

See [Development](docs/development.md), [Architecture](docs/architecture.md),
[Codex structured storage](docs/codex-storage.md), [XDG contract](docs/xdg-contract.md),
and the [delivery roadmap](docs/roadmap.md) before extending the project.
