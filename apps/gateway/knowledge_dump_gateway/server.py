from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .config import GatewayConfig
from .schema import SCHEMA_VERSION
from .storage import MockStorageAdapter, StorageAdapter, multipart_part_size, storage_from_config
from .store import AuthContext, Catalog, _UNSET, utc_now


MAX_JSON_BYTES = 1_048_576


class KnowledgeDumpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], catalog: Catalog, storage: StorageAdapter):
        self.catalog = catalog
        self.storage = storage
        super().__init__(address, KnowledgeDumpHandler)


class KnowledgeDumpHandler(BaseHTTPRequestHandler):
    server: KnowledgeDumpServer
    server_version = "KnowledgeDumpGateway/0.3"

    def log_message(self, format_string: str, *args: object) -> None:
        del format_string
        status = args[1] if len(args) > 1 else "-"
        size = args[2] if len(args) > 2 else "-"
        # Presigned mock URLs contain bearer-equivalent query tokens; never log them.
        print(f'{self.address_string()} - "{self.command} {urlparse(self.path).path}" {status} {size}')

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Range")
        self.send_header("Access-Control-Expose-Headers", "ETag, Content-Range, Accept-Ranges")
        self.send_header("Access-Control-Max-Age", "600")
        self._security_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/v1/health":
            self._json({
                "status": "healthy",
                "service": "knowledge-dump-gateway",
                "mode": self.server.catalog.config.mode,
                "database": self.server.catalog.database_backend,
                "schemaVersion": SCHEMA_VERSION,
                "checkedAt": utc_now(),
            })
            return
        if path == "/api/v1/storage/mock/download":
            self._mock_download((parse_qs(parsed.query).get("token") or [""])[0])
            return

        auth = self._auth()
        if not auth:
            return
        try:
            if path == "/api/v1/auth/session":
                self._json({"account": auth.account, "device": auth.device})
            elif path == "/api/v1/devices":
                self._json({"devices": self.server.catalog.list_devices(auth.account_id), "currentDeviceId": auth.device_id})
            elif path == "/api/v1/storage/health":
                self._storage_health(auth)
            elif path == "/api/v1/files":
                query = parse_qs(parsed.query)
                parent_id = (query.get("parentId") or [None])[0] or None
                status = (query.get("status") or ["active"])[0]
                search = (query.get("search") or [""])[0]
                self._json({"files": self.server.catalog.list_files(auth.account_id, parent_id=parent_id, status=status, search=search)})
            elif path == "/api/v1/activity":
                self._json({"activity": self.server.catalog.list_activity(auth.account_id)})
            elif path.startswith("/api/v1/uploads/"):
                upload = self.server.catalog.upload_session(auth.account_id, path.split("/")[-1])
                if upload:
                    self._json({"upload": upload})
                else:
                    self._error(HTTPStatus.NOT_FOUND, "upload_not_found")
            elif path.startswith("/api/v1/files/") and path.endswith("/versions"):
                file_id = path.split("/")[-2]
                versions = self.server.catalog.list_versions(auth.account_id, file_id)
                if versions is None:
                    self._error(HTTPStatus.NOT_FOUND, "file_not_found")
                else:
                    self._json({"versions": versions})
            else:
                self._error(HTTPStatus.NOT_FOUND, "route_not_found")
        except ValueError as exc:
            self._value_error(exc)

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/v1/auth/login":
            self._login()
            return
        if path == "/api/v1/auth/refresh":
            self._refresh()
            return

        auth = self._auth()
        if not auth:
            return
        if path == "/api/v1/auth/logout":
            self.server.catalog.logout(self._bearer_token())
            self._json({"loggedOut": True})
            return
        payload = self._read_json()
        if payload is None:
            return
        try:
            if path == "/api/v1/uploads":
                self._initiate_upload(auth, payload)
            elif path.startswith("/api/v1/uploads/") and "/parts/" in path and path.endswith("/complete"):
                segments = path.split("/")
                self._record_upload_part(auth, segments[-4], int(segments[-2]), payload)
            elif path.startswith("/api/v1/uploads/") and path.endswith("/parts"):
                self._issue_upload_parts(auth, path.split("/")[-2], payload)
            elif path.startswith("/api/v1/uploads/") and path.endswith("/complete"):
                self._complete_upload(auth, path.split("/")[-2])
            elif path.startswith("/api/v1/files/") and path.endswith("/download"):
                self._download(auth, path.split("/")[-2])
            elif path == "/api/v1/folders":
                folder = self.server.catalog.create_folder(
                    auth.account_id,
                    str(payload.get("name") or ""),
                    str(payload.get("parentId") or "") or None,
                    auth.device_id,
                )
                self._json({"file": folder}, HTTPStatus.CREATED)
            elif path == "/api/v1/files":
                self._error(HTTPStatus.GONE, "upload_session_required")
            elif path.startswith("/api/v1/files/") and path.endswith("/archive"):
                self._status_action(auth, path, "archived")
            elif path.startswith("/api/v1/files/") and path.endswith("/restore"):
                self._status_action(auth, path, "active")
            else:
                self._error(HTTPStatus.NOT_FOUND, "route_not_found")
        except (ValueError, TypeError) as exc:
            self._value_error(exc)
        except Exception:
            self._error(HTTPStatus.BAD_GATEWAY, "storage_provider_error")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path.startswith("/api/v1/storage/mock/uploads/") or "/parts/" not in path:
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        if not isinstance(self.server.storage, MockStorageAdapter):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        segments = path.split("/")
        try:
            upload_id = segments[-3]
            part_number = int(segments[-1])
        except (ValueError, IndexError):
            self._error(HTTPStatus.BAD_REQUEST, "upload_part_number_invalid")
            return
        token = (parse_qs(parsed.query).get("token") or [""])[0]
        record = self.server.catalog.validate_mock_part_token(upload_id, part_number, token)
        if not record:
            self._error(HTTPStatus.FORBIDDEN, "upload_part_grant_invalid")
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length != int(record["expected_part_size"]):
            self._error(HTTPStatus.BAD_REQUEST, "upload_part_size_mismatch")
            return
        etag = self.server.storage.put_part(record["provider_upload_id"], part_number, self.rfile.read(length))
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self._security_headers()
        self.send_header("ETag", etag)
        self.send_header("Access-Control-Expose-Headers", "ETag")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        auth = self._auth()
        if not auth:
            return
        if not path.startswith("/api/v1/files/"):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        payload = self._read_json()
        if payload is None:
            return
        parent_id: str | None | object = _UNSET
        if "parentId" in payload:
            parent_id = str(payload.get("parentId") or "") or None
        try:
            item = self.server.catalog.update_file(
                auth.account_id,
                path.split("/")[-1],
                name=str(payload["name"]) if "name" in payload else None,
                parent_id=parent_id,
                actor_device_id=auth.device_id,
            )
        except ValueError as exc:
            self._value_error(exc)
            return
        if not item:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"file": item})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        auth = self._auth()
        if not auth:
            return
        if path.startswith("/api/v1/devices/"):
            device_id = path.split("/")[-1]
            if not self.server.catalog.revoke_device(auth.account_id, device_id, auth.device_id):
                self._error(HTTPStatus.NOT_FOUND, "device_not_found")
                return
            self._json({"revoked": True, "deviceId": device_id})
            return
        if path.startswith("/api/v1/uploads/"):
            self._abort_upload(auth, path.split("/")[-1])
            return
        if not path.startswith("/api/v1/files/"):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        try:
            file_id = path.split("/")[-1]
            record = self.server.catalog.file_storage_record(auth.account_id, file_id)
            if record and record["object_key"]:
                self.server.storage.delete(record["object_key"])
            deleted = self.server.catalog.purge(auth.account_id, file_id, auth.device_id)
        except ValueError as exc:
            self._value_error(exc)
            return
        except Exception:
            self._error(HTTPStatus.BAD_GATEWAY, "storage_provider_error")
            return
        if not deleted:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"deleted": True})

    def _login(self) -> None:
        payload = self._read_json()
        if payload is None:
            return
        try:
            result = self.server.catalog.login(
                str(payload.get("email") or ""),
                str(payload.get("password") or ""),
                requested_device_id=str(payload.get("deviceId") or "") or None,
                device_label=str(payload.get("deviceLabel") or "Knowledge Dump workstation"),
                platform=str(payload.get("platform") or "unknown"),
            )
        except ValueError as exc:
            self._value_error(exc)
            return
        if not result:
            self._error(HTTPStatus.UNAUTHORIZED, "credentials_invalid")
            return
        self._json(result)

    def _refresh(self) -> None:
        payload = self._read_json()
        if payload is None:
            return
        result = self.server.catalog.refresh(str(payload.get("refreshToken") or ""))
        if not result:
            self._error(HTTPStatus.UNAUTHORIZED, "refresh_token_invalid")
            return
        self._json(result)

    def _storage_health(self, auth: AuthContext) -> None:
        started = time.perf_counter()
        quota = self.server.catalog.quota(auth.account_id)
        try:
            provider_ready = self.server.storage.health()
        except Exception:
            provider_ready = False
        self._json({
            "gateway": "healthy" if provider_ready else "degraded",
            "authenticated": True,
            "provider": self.server.catalog.config.storage_provider,
            "providerReachable": provider_ready,
            "readAccess": provider_ready,
            "writeAccess": provider_ready,
            "latencyMs": max(1, round((time.perf_counter() - started) * 1000)),
            "checkedAt": utc_now(),
            "usedBytes": quota["usedBytes"],
            "quotaBytes": quota["maxBytes"],
            "usedObjects": quota["usedObjects"],
            "quotaObjects": quota["maxObjects"],
            "database": self.server.catalog.database_backend,
        })

    def _initiate_upload(self, auth: AuthContext, payload: dict[str, Any]) -> None:
        name = str(payload.get("name") or "")
        parent_id = str(payload.get("parentId") or "") or None
        kind = str(payload.get("kind") or "other")
        mime_type = str(payload.get("mimeType") or "") or None
        size_bytes = int(payload.get("sizeBytes") if payload.get("sizeBytes") is not None else -1)
        part_size = multipart_part_size(size_bytes, self.server.catalog.config.multipart_part_bytes)
        total_parts = max(1, (size_bytes + part_size - 1) // part_size)
        object_key = f"objects/{auth.account_id}/{uuid.uuid4().hex}"
        provider_upload_id = self.server.storage.create_multipart_upload(object_key, mime_type)
        try:
            upload = self.server.catalog.initiate_upload(
                auth.account_id,
                auth.device_id,
                name=name,
                parent_id=parent_id,
                kind=kind,
                mime_type=mime_type,
                size_bytes=size_bytes,
                object_key=object_key,
                provider_upload_id=provider_upload_id,
                part_size=part_size,
                total_parts=total_parts,
            )
        except Exception:
            self.server.storage.abort_multipart_upload(object_key, provider_upload_id)
            raise
        self._json({"upload": upload}, HTTPStatus.CREATED)

    def _issue_upload_parts(self, auth: AuthContext, upload_id: str, payload: dict[str, Any]) -> None:
        raw_numbers = payload.get("partNumbers")
        if not isinstance(raw_numbers, list) or not raw_numbers or len(raw_numbers) > 25:
            raise ValueError("upload_part_batch_invalid")
        part_numbers = sorted({int(value) for value in raw_numbers})
        if len(part_numbers) != len(raw_numbers):
            raise ValueError("upload_part_batch_invalid")
        record = self.server.catalog.active_upload_provider_record(auth.account_id, upload_id)
        expires_at = self._transfer_expiry()
        grants = []
        for part_number in part_numbers:
            if part_number < 1 or part_number > int(record["total_parts"]):
                raise ValueError("upload_part_number_invalid")
            if isinstance(self.server.storage, MockStorageAdapter):
                token = self.server.catalog.security.new_token()
                self.server.catalog.issue_mock_part_token(auth.account_id, upload_id, part_number, token, expires_at)
                url = f"/v1/storage/mock/uploads/{upload_id}/parts/{part_number}?token={quote(token)}"
            else:
                url = self.server.storage.presign_upload_part(
                    record["object_key"],
                    record["provider_upload_id"],
                    part_number,
                    self.server.catalog.config.transfer_url_seconds,
                )
            grants.append({"partNumber": part_number, "url": url, "method": "PUT", "headers": {}, "expiresAt": expires_at})
        self._json({"parts": grants})

    def _record_upload_part(self, auth: AuthContext, upload_id: str, part_number: int, payload: dict[str, Any]) -> None:
        upload = self.server.catalog.record_upload_part(
            auth.account_id,
            upload_id,
            part_number,
            str(payload.get("etag") or ""),
            int(payload.get("sizeBytes") if payload.get("sizeBytes") is not None else -1),
        )
        self._json({"upload": upload})

    def _complete_upload(self, auth: AuthContext, upload_id: str) -> None:
        current = self.server.catalog.upload_session(auth.account_id, upload_id)
        if not current:
            raise ValueError("upload_not_found")
        if current["status"] == "completed" and current["fileId"]:
            file_item = self.server.catalog.get_file(auth.account_id, current["fileId"])
            if not file_item:
                raise ValueError("file_not_found")
            self._json({"file": file_item, "upload": current})
            return
        prepared = self.server.catalog.prepare_upload_completion(auth.account_id, upload_id)
        try:
            observed = self.server.storage.complete_multipart_upload(
                prepared["object_key"],
                prepared["provider_upload_id"],
                prepared["parts"],
            )
        except Exception:
            try:
                observed = self.server.storage.head(prepared["object_key"])
            except Exception:
                self.server.catalog.reset_upload_after_completion_error(auth.account_id, upload_id, "storage_provider_error")
                raise
        try:
            file_item = self.server.catalog.finalize_upload(
                auth.account_id,
                upload_id,
                observed_size=observed.size_bytes,
                observed_etag=observed.etag,
            )
        except Exception:
            self.server.storage.delete(prepared["object_key"])
            self.server.catalog.reset_upload_after_completion_error(auth.account_id, upload_id, "upload_verification_failed")
            raise
        self._json({"file": file_item, "upload": self.server.catalog.upload_session(auth.account_id, upload_id)})

    def _abort_upload(self, auth: AuthContext, upload_id: str) -> None:
        record = self.server.catalog.upload_provider_record(auth.account_id, upload_id)
        if not record:
            self._error(HTTPStatus.NOT_FOUND, "upload_not_found")
            return
        try:
            if record["status"] not in {"aborted", "expired", "completed"}:
                self.server.storage.abort_multipart_upload(record["object_key"], record["provider_upload_id"])
            self.server.catalog.abort_upload(auth.account_id, upload_id, auth.device_id)
        except ValueError as exc:
            self._value_error(exc)
            return
        except Exception:
            self._error(HTTPStatus.BAD_GATEWAY, "storage_provider_error")
            return
        self._json({"aborted": True, "uploadId": upload_id})

    def _status_action(self, auth: AuthContext, path: str, status: str) -> None:
        file_id = path.split("/")[-2]
        item = self.server.catalog.set_status(auth.account_id, file_id, status, auth.device_id)
        if not item:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"file": item})

    def _download(self, auth: AuthContext, file_id: str) -> None:
        record = self.server.catalog.file_storage_record(auth.account_id, file_id)
        if not record or record["kind"] == "folder" or not record["object_key"]:
            raise ValueError("download_not_found")
        expires_at = self._transfer_expiry()
        if isinstance(self.server.storage, MockStorageAdapter):
            token = self.server.catalog.security.new_token()
            self.server.catalog.create_download_grant(auth.account_id, file_id, token, expires_at)
            url = f"/v1/storage/mock/download?token={quote(token)}"
        else:
            url = self.server.storage.presign_download(
                record["object_key"],
                PurePosixPath(record["name"]).name,
                record["mime_type"],
                self.server.catalog.config.transfer_url_seconds,
            )
        self.server.catalog.record_download_authorized(auth.account_id, file_id, auth.device_id)
        self._json({"url": url, "method": "GET", "headers": {}, "expiresAt": expires_at})

    def _mock_download(self, token: str) -> None:
        if not isinstance(self.server.storage, MockStorageAdapter):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        grant = self.server.catalog.validate_download_grant(token)
        if not grant:
            self._error(HTTPStatus.FORBIDDEN, "download_grant_invalid")
            return
        size = int(grant["size_bytes"])
        start, end = 0, max(0, size - 1)
        status = HTTPStatus.OK
        range_header = self.headers.get("Range", "")
        if range_header:
            try:
                start, end = self._parse_range(range_header, size)
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT
        content = self.server.storage.read(grant["object_key"], start, end)
        self.send_response(status)
        self._cors_headers()
        self._security_headers()
        self.send_header("Content-Type", grant["mime_type"] or mimetypes.guess_type(grant["name"])[0] or "application/octet-stream")
        self.send_header("Content-Disposition", f"attachment; filename={json.dumps(PurePosixPath(grant['name']).name)}")
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(content)

    @staticmethod
    def _parse_range(value: str, size: int) -> tuple[int, int]:
        if size < 1 or not value.startswith("bytes=") or "," in value:
            raise ValueError("range_invalid")
        start_text, separator, end_text = value[6:].partition("-")
        if not separator:
            raise ValueError("range_invalid")
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            length = int(end_text)
            if length < 1:
                raise ValueError("range_invalid")
            start = max(0, size - length)
            end = size - 1
        if start < 0 or start >= size or end < start:
            raise ValueError("range_invalid")
        return start, min(end, size - 1)

    def _transfer_expiry(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=self.server.catalog.config.transfer_url_seconds)).isoformat()

    def _auth(self) -> AuthContext | None:
        context = self.server.catalog.authenticate(self._bearer_token())
        if not context:
            self._error(HTTPStatus.UNAUTHORIZED, "authentication_required")
        return context

    def _bearer_token(self) -> str:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return ""
        return authorization[7:].strip()

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_JSON_BYTES:
            self._error(HTTPStatus.BAD_REQUEST, "request_body_invalid")
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "request_json_invalid")
            return None
        if not isinstance(payload, dict):
            self._error(HTTPStatus.BAD_REQUEST, "request_json_invalid")
            return None
        return payload

    def _value_error(self, exc: Exception) -> None:
        code = str(exc)
        if code.startswith("quota_"):
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, code)
        elif code == "device_revoked":
            self._error(HTTPStatus.FORBIDDEN, code)
        elif code in {"folder_not_empty", "upload_parts_incomplete", "upload_not_active", "upload_already_completed", "upload_not_completing"}:
            self._error(HTTPStatus.CONFLICT, code)
        elif code in {"upload_not_found", "download_not_found", "file_not_found"}:
            self._error(HTTPStatus.NOT_FOUND, code)
        elif code == "upload_expired":
            self._error(HTTPStatus.GONE, code)
        else:
            self._error(HTTPStatus.BAD_REQUEST, code)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self._security_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: HTTPStatus, code: str) -> None:
        self._json({"error": code}, status)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

    def _cors_headers(self) -> None:
        allowed = {
            item.strip()
            for item in os.environ.get(
                "KNOWLEDGE_DUMP_ALLOWED_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173,tauri://localhost",
            ).split(",")
            if item.strip()
        }
        origin = self.headers.get("Origin", "")
        if origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    catalog: Catalog | None = None,
    config: GatewayConfig | None = None,
    storage: StorageAdapter | None = None,
) -> KnowledgeDumpServer:
    resolved_catalog = catalog or Catalog(config=config)
    return KnowledgeDumpServer((host, port), resolved_catalog, storage or storage_from_config(resolved_catalog.config))


def cleanup_expired_uploads(catalog: Catalog, storage: StorageAdapter) -> int:
    cleaned = 0
    for record in catalog.expired_uploads():
        try:
            storage.abort_multipart_upload(record["object_key"], record["provider_upload_id"])
            catalog.abort_upload(record["account_id"], record["id"], record["device_id"], status="expired")
            cleaned += 1
        except Exception:
            continue
    catalog.cleanup_expired_download_grants()
    return cleaned
