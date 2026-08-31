# Knowledge Dump

Knowledge Dump is a standalone Ubuntu-native cloud file manager. It provides a
desktop workspace for organizing, uploading, downloading, and recovering files
through an independently deployed Knowledge Dump Gateway.

The repository intentionally does not depend on BookOS or its gateway.

## Development milestone

The current foundation includes:

- a React desktop interface with authentication, file management, transfers,
  storage health, and settings surfaces;
- a PostgreSQL/SQLite account and catalog gateway with secure rotating sessions;
- shared TypeScript protocol definitions;
- a Tauri/WebKitGTK native shell scaffold;
- DigitalOcean Spaces adapter and deployment contracts;
- Debian packaging and XDG filesystem documentation.

The gateway stores account-scoped, versioned file metadata while object bytes
remain represented by development placeholders. Phase 3 replaces that byte path
with presigned DigitalOcean Spaces transfers without changing the desktop API.

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

The browser development loop uses the real React client against the account and
catalog gateway on an XDG-backed SQLite database. The same schema supports
PostgreSQL deployments. `npm run dev:native` opens the client in WebKitGTK after
the gateway is running. Object bytes remain phase 3 work; uploads currently
persist versioned metadata and expose a placeholder download.

See [Development](docs/development.md), [Architecture](docs/architecture.md),
[XDG contract](docs/xdg-contract.md), and the [delivery roadmap](docs/roadmap.md)
before extending the project.
