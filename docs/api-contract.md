# API contract V1

All authenticated endpoints accept `Authorization: Bearer <session-token>`.

```text
GET    /api/v1/health
POST   /api/v1/auth/login
GET    /api/v1/auth/session
POST   /api/v1/auth/logout
GET    /api/v1/storage/health
GET    /api/v1/files
POST   /api/v1/folders
POST   /api/v1/files
PATCH  /api/v1/files/{file_id}
POST   /api/v1/files/{file_id}/archive
POST   /api/v1/files/{file_id}/restore
DELETE /api/v1/files/{file_id}
GET    /api/v1/files/{file_id}/download
GET    /api/v1/activity
```

Production transfer endpoints will add multipart registration, part URLs,
completion, abort, and byte-range downloads. The mock `POST /files` endpoint
accepts safe metadata only and represents a completed upload.
