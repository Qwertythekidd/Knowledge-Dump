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

from .store import Catalog, _UNSET, utc_now


MAX_JSON_BYTES = 1_048_576
QUOTA_BYTES = 250 * 1024 * 1024 * 1024


class KnowledgeDumpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], catalog: Catalog):
        self.catalog = catalog
        super().__init__(address, KnowledgeDumpHandler)


class KnowledgeDumpHandler(BaseHTTPRequestHandler):
    server: KnowledgeDumpServer
    server_version = "KnowledgeDumpMock/0.1"

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} - {format_string % args}")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/v1/health":
            self._json({"status": "healthy", "service": "knowledge-dump-gateway", "mode": "mock", "checkedAt": utc_now()})
            return
        account = self._account()
        if not account:
            return
        if path == "/api/v1/auth/session":
            self._json({"account": account})
        elif path == "/api/v1/storage/health":
            started = time.perf_counter()
            used = self.server.catalog.usage()
            self._json({
                "gateway": "healthy",
                "authenticated": True,
                "provider": "mock",
                "providerReachable": True,
                "readAccess": True,
                "writeAccess": True,
                "latencyMs": max(1, round((time.perf_counter() - started) * 1000)),
                "checkedAt": utc_now(),
                "usedBytes": used,
                "quotaBytes": QUOTA_BYTES,
            })
        elif path == "/api/v1/files":
            query = parse_qs(parsed.query)
            parent_id = (query.get("parentId") or [None])[0] or None
            status = (query.get("status") or ["active"])[0]
            search = (query.get("search") or [""])[0]
            self._json({"files": self.server.catalog.list_files(parent_id=parent_id, status=status, search=search)})
        elif path == "/api/v1/activity":
            self._json({"activity": self.server.catalog.list_activity()})
        elif path.startswith("/api/v1/files/") and path.endswith("/download"):
            file_id = path.split("/")[-2]
            self._download(file_id)
        else:
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/v1/auth/login":
            payload = self._read_json()
            if payload is None:
                return
            result = self.server.catalog.login(str(payload.get("email") or ""), str(payload.get("password") or ""))
            if not result:
                self._error(HTTPStatus.UNAUTHORIZED, "credentials_invalid")
                return
            self._json(result)
            return
        account = self._account()
        if not account:
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
                    str(payload.get("name") or ""),
                    str(payload.get("parentId") or "") or None,
                )
                self._json({"file": folder}, HTTPStatus.CREATED)
            elif path == "/api/v1/files":
                file_item = self.server.catalog.create_file(
                    name=str(payload.get("name") or ""),
                    parent_id=str(payload.get("parentId") or "") or None,
                    kind=str(payload.get("kind") or "other"),
                    mime_type=str(payload.get("mimeType") or "") or None,
                    size_bytes=int(payload.get("sizeBytes") or 0),
                )
                self._json({"file": file_item}, HTTPStatus.CREATED)
            elif path.startswith("/api/v1/files/") and path.endswith("/archive"):
                self._status_action(path, "archived")
            elif path.startswith("/api/v1/files/") and path.endswith("/restore"):
                self._status_action(path, "active")
            else:
                self._error(HTTPStatus.NOT_FOUND, "route_not_found")
        except (ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        account = self._account()
        if not account:
            return
        if not path.startswith("/api/v1/files/"):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        payload = self._read_json()
        if payload is None:
            return
        file_id = path.split("/")[-1]
        parent_id: str | None | object = _UNSET
        if "parentId" in payload:
            parent_id = str(payload.get("parentId") or "") or None
        try:
            item = self.server.catalog.update_file(
                file_id,
                name=str(payload["name"]) if "name" in payload else None,
                parent_id=parent_id,
            )
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not item:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"file": item})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        account = self._account()
        if not account:
            return
        if not path.startswith("/api/v1/files/"):
            self._error(HTTPStatus.NOT_FOUND, "route_not_found")
            return
        try:
            deleted = self.server.catalog.purge(path.split("/")[-1])
        except ValueError as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
            return
        if not deleted:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"deleted": True})

    def _status_action(self, path: str, status: str) -> None:
        file_id = path.split("/")[-2]
        item = self.server.catalog.set_status(file_id, status)
        if not item:
            self._error(HTTPStatus.NOT_FOUND, "file_not_found")
            return
        self._json({"file": item})

    def _download(self, file_id: str) -> None:
        item = self.server.catalog.get_file(file_id)
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
        self.send_header("Content-Type", item.get("mimeType") or mimetypes.guess_type(item["name"])[0] or "application/octet-stream")
        self.send_header("Content-Disposition", f"attachment; filename={json.dumps(PurePosixPath(item['name']).name)}")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(content)

    def _account(self) -> dict[str, Any] | None:
        account = self.server.catalog.authenticate(self._bearer_token())
        if not account:
            self._error(HTTPStatus.UNAUTHORIZED, "authentication_required")
        return account

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

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: HTTPStatus, code: str) -> None:
        self._json({"error": code}, status)

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


def create_server(*, host: str = "127.0.0.1", port: int = 8787, catalog: Catalog | None = None) -> KnowledgeDumpServer:
    return KnowledgeDumpServer((host, port), catalog or Catalog())
