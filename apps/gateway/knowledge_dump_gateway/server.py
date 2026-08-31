from __future__ import annotations

import json
import mimetypes
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import GatewayConfig
from .store import AuthContext, Catalog, _UNSET, utc_now


MAX_JSON_BYTES = 1_048_576


class KnowledgeDumpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], catalog: Catalog):
        self.catalog = catalog
        super().__init__(address, KnowledgeDumpHandler)


class KnowledgeDumpHandler(BaseHTTPRequestHandler):
    server: KnowledgeDumpServer
    server_version = "KnowledgeDumpGateway/0.2"

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} - {format_string % args}")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
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
                "schemaVersion": 2,
                "checkedAt": utc_now(),
            })
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
            elif path.startswith("/api/v1/files/") and path.endswith("/versions"):
                file_id = path.split("/")[-2]
                versions = self.server.catalog.list_versions(auth.account_id, file_id)
                if versions is None:
                    self._error(HTTPStatus.NOT_FOUND, "file_not_found")
                else:
                    self._json({"versions": versions})
            elif path.startswith("/api/v1/files/") and path.endswith("/download"):
                self._download(auth, path.split("/")[-2])
            else:
                self._error(HTTPStatus.NOT_FOUND, "route_not_found")
        except ValueError as exc:
            self._value_error(exc)

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/v1/auth/login":
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
            return
        if path == "/api/v1/auth/refresh":
            payload = self._read_json()
            if payload is None:
                return
            result = self.server.catalog.refresh(str(payload.get("refreshToken") or ""))
            if not result:
                self._error(HTTPStatus.UNAUTHORIZED, "refresh_token_invalid")
                return
            self._json(result)
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
            if path == "/api/v1/folders":
                folder = self.server.catalog.create_folder(
                    auth.account_id,
                    str(payload.get("name") or ""),
                    str(payload.get("parentId") or "") or None,
                    auth.device_id,
                )
                self._json({"file": folder}, HTTPStatus.CREATED)
            elif path == "/api/v1/files":
                file_item = self.server.catalog.create_file(
                    auth.account_id,
                    name=str(payload.get("name") or ""),
                    parent_id=str(payload.get("parentId") or "") or None,
                    kind=str(payload.get("kind") or "other"),
                    mime_type=str(payload.get("mimeType") or "") or None,
                    size_bytes=int(payload.get("sizeBytes") or 0),
                    actor_device_id=auth.device_id,
                )
                self._json({"file": file_item}, HTTPStatus.CREATED)
            elif path.startswith("/api/v1/files/") and path.endswith("/archive"):
                self._status_action(auth, path, "archived")
            elif path.startswith("/api/v1/files/") and path.endswith("/restore"):
                self._status_action(auth, path, "active")
            else:
                self._error(HTTPStatus.NOT_FOUND, "route_not_found")
        except (ValueError, TypeError) as exc:
            self._value_error(exc)

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
        if not path.startswith("/api/v1/files/"):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        try:
            deleted = self.server.catalog.purge(auth.account_id, path.split("/")[-1], auth.device_id)
        except ValueError as exc:
            self._value_error(exc)
            return
        if not deleted:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"deleted": True})

    def _storage_health(self, auth: AuthContext) -> None:
        started = time.perf_counter()
        quota = self.server.catalog.quota(auth.account_id)
        provider = self.server.catalog.config.storage_provider
        provider_ready = provider == "mock"
        self._json({
            "gateway": "healthy",
            "authenticated": True,
            "provider": provider,
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

    def _status_action(self, auth: AuthContext, path: str, status: str) -> None:
        file_id = path.split("/")[-2]
        item = self.server.catalog.set_status(auth.account_id, file_id, status, auth.device_id)
        if not item:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"file": item})

    def _download(self, auth: AuthContext, file_id: str) -> None:
        item = self.server.catalog.get_file(auth.account_id, file_id)
        if not item or item["kind"] == "folder":
            self._error(HTTPStatus.NOT_FOUND, "download_not_found")
            return
        content = (
            "Knowledge Dump development placeholder\n\n"
            f"File: {item['name']}\n"
            f"Object ID: {item['id']}\n"
            "Production releases download encrypted bytes from object storage.\n"
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self._security_headers()
        self.send_header("Content-Type", item.get("mimeType") or mimetypes.guess_type(item["name"])[0] or "application/octet-stream")
        self.send_header("Content-Disposition", f"attachment; filename={json.dumps(PurePosixPath(item['name']).name)}")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(content)

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
        elif code == "folder_not_empty":
            self._error(HTTPStatus.CONFLICT, code)
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
) -> KnowledgeDumpServer:
    return KnowledgeDumpServer((host, port), catalog or Catalog(config=config))
