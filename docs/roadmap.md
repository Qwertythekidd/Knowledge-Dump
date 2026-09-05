# Delivery roadmap

The scaffold represents every planned boundary in the interface while keeping
unfinished security and storage work explicit.

## Phase 1: native development foundation - implemented

- standalone repository and protocol package;
- React interface shared by browser development and Tauri/WebKitGTK;
- XDG filesystem contract and Debian packaging;
- functional SQLite-backed mock gateway and integration tests.

## Phase 2: account and catalog gateway - implemented

The gateway now supports PostgreSQL and SQLite through one schema, Argon2id
password hashing, HMAC-hashed rotating sessions, device registration and
revocation, account quotas, account-scoped virtual paths, immutable metadata
versions, and durable audit events. Demo bootstrap is development-only and
production accounts are operator-provisioned.

## Phase 3: DigitalOcean Spaces transfers - implemented

The `SpacesStorageAdapter`, durable multipart sessions, batched short-lived
part URLs, resumable ETag checkpoints, object verification, range downloads,
abort/expiry cleanup, and direct-transfer desktop queue are implemented.
DigitalOcean infrastructure remains configuration, not another project.

## Phase 4: encryption, sync, and recovery - surfaces prepared

Add per-device key material in Secret Service, client-side content encryption,
encrypted manifests, sync cursors, conflict copies, resumable transfers, and
device recovery. The protocol must version encryption formats before real user
objects are accepted.

The local half of Codex recovery is implemented as a structured, refreshable
collection with SHA-256 verification and isolated restore. Publishing that
collection remains blocked until client-side encryption is complete.

## Phase 5: native release - packaging prepared

Build and sign the Debian package, add repository/update metadata, harden the
desktop CSP, package fonts locally, run Ubuntu integration tests, and establish
backup/restore procedures for PostgreSQL and Spaces metadata.

Real files are now supported, but secrets and private archives must wait for
phase 4 client-side encryption. No mock behavior should silently become
production behavior. Each deferred feature is named in the UI or documentation
and has a stable replacement seam.
