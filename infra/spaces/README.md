# DigitalOcean Spaces boundary

DigitalOcean Spaces is S3-compatible object storage, not a separately deployed
Knowledge Dump service. It therefore does not need its own application project.
The production gateway will use an adapter configured with:

```text
KNOWLEDGE_DUMP_SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com
KNOWLEDGE_DUMP_SPACES_REGION=nyc3
KNOWLEDGE_DUMP_SPACES_BUCKET=knowledge-dump-production
KNOWLEDGE_DUMP_SPACES_ACCESS_KEY_ID=...
KNOWLEDGE_DUMP_SPACES_SECRET_ACCESS_KEY=...
```

Use a private Space, disable public listing and CDN access, and create a limited
Spaces key scoped to this bucket. Credentials belong on the gateway host only.
They must never be compiled into the desktop application.

## Planned production flow

1. The desktop requests an upload session from the Knowledge Dump Gateway.
2. The gateway validates account quota and creates an opaque object key.
3. The gateway returns a short-lived presigned multipart upload request.
4. The desktop transfers encrypted bytes directly to Spaces.
5. The desktop completes the transfer through the gateway.
6. The gateway verifies the object and commits its metadata in PostgreSQL.

The same pattern applies to downloads: the gateway authorizes a short-lived
object read while retaining account, path, version, and audit ownership.
