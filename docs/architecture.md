# Architecture

Knowledge Dump has three independent runtime boundaries.

```text
Ubuntu desktop app
  | HTTPS bearer session
  v
Knowledge Dump Gateway
  | short-lived presigned requests
  v
S3-compatible object storage
```

## Desktop

The desktop owns presentation, local cache state, transfer progress, device
identity, and client-side encryption in the final implementation. It never
stores DigitalOcean credentials. The React app is shared between browser
development and the Tauri/WebKitGTK native shell.

## Gateway

The gateway owns user accounts, sessions, safe file metadata, provider
configuration, device records, transfer authorization, audit events, and quota
enforcement. It never proxies large object bytes in production. Upload and
download data moves between the desktop and object storage using short-lived
presigned URLs.

The account, catalog, and transfer schema runs on PostgreSQL in deployment and
SQLite in local development. Durable multipart checkpoints make interrupted
uploads resumable. Provider completion and object size verification happen
before a file becomes visible in the catalog.

## Object storage

DigitalOcean Spaces is infrastructure, not another application repository.
Provider-specific behavior lives behind a storage adapter in the gateway. A
private Space should be created specifically for Knowledge Dump, with its CDN
disabled and a limited access key stored only by the gateway.

## Production data ownership

- PostgreSQL: users, sessions, device registrations, virtual folders, file
  records, object versions, transfer sessions, quotas, and audit events.
- Spaces: private opaque immutable file objects. Client-side encryption and
  encrypted manifests arrive in phase 4.
- Desktop SQLite: local index, sync cursor, transfer resume state, and cache
  inventory.
- Ubuntu keyring: refresh token and device credentials.

File paths are virtual metadata. Storage keys are opaque identifiers and never
contain user-provided filenames.
