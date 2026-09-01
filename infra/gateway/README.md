# Gateway deployment foundation

The gateway is independently deployed from BookOS and from the desktop app.
Its production database is PostgreSQL; SQLite remains the local-development and
test backend. Both use the same SQLAlchemy Core schema.

Copy `.env.example` to a host-owned environment file and provide unique values
for the PostgreSQL password, token pepper, and limited Spaces key. Set
`KNOWLEDGE_DUMP_STORAGE_PROVIDER=digitalocean_spaces`. Do not commit these values.

```bash
cd infra/gateway
docker compose --env-file /secure/path/knowledge-dump-gateway.env up -d --build
```

The container binds only to loopback. Put Caddy or another TLS edge in front of
it and allow only the exact desktop/web origins needed by the deployment.
Run `knowledge-dump-gateway transfers cleanup-expired` hourly from the host in
addition to the Space lifecycle policy. Startup also attempts transfer cleanup.

## First account

Run account provisioning inside the gateway container. The password is read
without being placed in shell history:

```bash
docker compose exec gateway knowledge-dump-gateway account create \
  --email operator@example.com \
  --display-name "Primary operator" \
  --plan Personal \
  --seed-workspace
```
