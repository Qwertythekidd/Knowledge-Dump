# API contract V1

All authenticated endpoints accept `Authorization: Bearer <session-token>`.

```text
GET    /api/v1/health
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
GET    /api/v1/auth/session
POST   /api/v1/auth/logout
GET    /api/v1/devices
DELETE /api/v1/devices/{device_id}
GET    /api/v1/storage/health
GET    /api/v1/files
POST   /api/v1/folders
PATCH  /api/v1/files/{file_id}
POST   /api/v1/files/{file_id}/archive
POST   /api/v1/files/{file_id}/restore
DELETE /api/v1/files/{file_id}
POST   /api/v1/files/{file_id}/download
GET    /api/v1/files/{file_id}/versions
GET    /api/v1/activity
POST   /api/v1/uploads
GET    /api/v1/uploads/{upload_id}
POST   /api/v1/uploads/{upload_id}/parts
POST   /api/v1/uploads/{upload_id}/parts/{part_number}/complete
POST   /api/v1/uploads/{upload_id}/complete
DELETE /api/v1/uploads/{upload_id}
```

Accounts are operator-provisioned in V1. Access tokens are short-lived and
refresh tokens rotate on every use. Device revocation invalidates every session
issued to that workstation.

`POST /uploads` reserves quota and creates a provider multipart upload. Part
URLs are requested in batches of at most 25. After each direct object-store PUT,
the client reports the provider ETag and exact byte count. The visible file row
is created only after every part exists and the gateway verifies the completed
provider object's size.

`POST /files/{id}/download` returns a short-lived read grant rather than file
bytes. DigitalOcean transfers go directly to the private Space. The local mock
adapter exposes equivalent tokenized PUT/GET routes and supports HTTP byte
ranges so the same desktop flow is exercised in development.
