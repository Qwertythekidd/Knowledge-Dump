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

## Production flow

1. The desktop requests an upload session from the Knowledge Dump Gateway.
2. The gateway validates account quota and creates an opaque object key.
3. The gateway returns short-lived presigned URLs in bounded part batches.
4. The desktop transfers encrypted bytes directly to Spaces.
5. The desktop completes the transfer through the gateway.
6. The gateway verifies the object and commits its metadata in PostgreSQL.

The same pattern applies to downloads: the gateway authorizes a short-lived
object read while retaining account, path, version, and audit ownership.

Apply `cors.example.json` after replacing its web origin. Direct browser uploads
must allow `PUT` and expose `ETag`; without that exposed response header the
desktop intentionally refuses to finalize a part. Apply
`lifecycle.example.json` so abandoned provider uploads are removed after two
days, while the gateway expires its authorization session after 24 hours.

Example with the AWS CLI configured for the limited Spaces key:

```bash
aws s3api put-bucket-cors \
  --bucket knowledge-dump-production \
  --cors-configuration file://infra/spaces/cors.example.json \
  --endpoint-url https://nyc3.digitaloceanspaces.com

aws s3api put-bucket-lifecycle-configuration \
  --bucket knowledge-dump-production \
  --lifecycle-configuration file://infra/spaces/lifecycle.example.json \
  --endpoint-url https://nyc3.digitaloceanspaces.com
```
