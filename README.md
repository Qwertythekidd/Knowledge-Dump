# Knowledge Dump

Knowledge Dump is a standalone Ubuntu-native cloud file manager. It provides a
desktop workspace for organizing, uploading, downloading, and recovering files
through an independently deployed Knowledge Dump Gateway.

The repository intentionally does not depend on BookOS or its gateway.

## Development milestone

This first milestone includes:

- a React desktop interface with authentication, file management, transfers,
  storage health, and settings surfaces;
- a runnable mock gateway with bearer sessions and an XDG-backed SQLite catalog;
- shared TypeScript protocol definitions;
- a Tauri/WebKitGTK native shell scaffold;
- DigitalOcean Spaces adapter and deployment contracts;
- Debian packaging and XDG filesystem documentation.

The mock gateway stores file metadata and placeholder object content locally.
It is designed to be replaced by PostgreSQL and presigned DigitalOcean Spaces
transfers without changing the desktop API contract.

## Quick start

Requirements: Node.js 20+, npm, and Python 3.10+.

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5173` and sign in with:

```text
Email: demo@knowledge-dump.local
Password: knowledge
```

Run verification with:

```bash
npm run check
```

The browser development loop uses the real React client against a functional
local gateway mock. `npm run dev:native` opens the same client in the native
WebKitGTK shell after the mock gateway is running. Object bytes and production
identity are intentionally deferred; uploads currently persist catalog metadata
and expose a placeholder download so the full interface can be exercised.

See [Development](docs/development.md), [Architecture](docs/architecture.md),
[XDG contract](docs/xdg-contract.md), and the [delivery roadmap](docs/roadmap.md)
before extending the project.
