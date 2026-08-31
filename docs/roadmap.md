# Delivery roadmap

The scaffold represents every planned boundary in the interface while keeping
unfinished security and storage work explicit.

## Phase 1: native development foundation - implemented

- standalone repository and protocol package;
- React interface shared by browser development and Tauri/WebKitGTK;
- XDG filesystem contract and Debian packaging;
- functional SQLite-backed mock gateway and integration tests.

## Phase 2: account and catalog gateway - interface mocked

Replace the demo account and bearer sessions with PostgreSQL-backed accounts,
password hashing, device registration, refresh-token rotation, quota records,
virtual paths, object versions, and durable audit events. The existing login,
library, activity, and health surfaces are the client contract for this work.

## Phase 3: DigitalOcean Spaces transfers - adapter prepared

Implement the `SpacesStorageAdapter`, multipart upload sessions, short-lived
presigned URLs, object verification, range downloads, and lifecycle cleanup.
Uploads in the scaffold show real queue/progress behavior but commit metadata
only. DigitalOcean infrastructure remains configuration, not another project.

## Phase 4: encryption, sync, and recovery - surfaces prepared

Add per-device key material in Secret Service, client-side content encryption,
encrypted manifests, sync cursors, conflict copies, resumable transfers, and
device recovery. The protocol must version encryption formats before real user
objects are accepted.

## Phase 5: native release - packaging prepared

Build and sign the Debian package, add repository/update metadata, harden the
desktop CSP, package fonts locally, run Ubuntu integration tests, and establish
backup/restore procedures for PostgreSQL and Spaces metadata.

No mock behavior should silently become production behavior. Each deferred
feature is named in the UI or documentation and has a stable replacement seam.
