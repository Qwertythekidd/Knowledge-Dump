# Gateway security model

## Credentials and sessions

- Passwords are hashed with Argon2id and automatically rehashed after a
  successful login when parameters change.
- Access and refresh tokens are random 48-byte URL-safe values. Only HMAC-SHA256
  hashes are stored in the database; the HMAC pepper is deployment-owned.
- Access tokens expire after 15 minutes by default. Refresh tokens rotate on
  every use and expire after 30 days by default.
- Refreshing replaces the session's previous access and refresh hashes, so
  replaying either old token fails.
- Logging out or revoking a workstation invalidates its server-side sessions.

The browser development client keeps both tokens in `sessionStorage`. The
native production client must move refresh tokens into Secret Service before
phase 5 release.

## Isolation and authorization

Every file, version, audit event, quota, device, and session is account-owned.
The authenticated account ID is derived from the bearer token and never from a
request body. Parent-folder validation also checks account ownership.

## Storage and secrets

The gateway never gives a desktop application the DigitalOcean master key.
Phase 3 will issue short-lived, account-scoped presigned transfers. Object keys
will be opaque and unrelated to user filenames.

Production mode fails closed when `KNOWLEDGE_DUMP_TOKEN_PEPPER` is missing.
Database passwords, token peppers, and Spaces credentials belong in host secret
storage and encrypted backups, not in this repository.
