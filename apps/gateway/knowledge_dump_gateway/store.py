from __future__ import annotations

import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import catalog_path


DEMO_EMAIL = "demo@knowledge-dump.local"
DEMO_PASSWORD = "knowledge"
DEMO_ACCOUNT_ID = "acct_demo"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


class Catalog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or catalog_path()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY,
                  account_id TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY,
                  account_id TEXT NOT NULL,
                  parent_id TEXT REFERENCES files(id) ON DELETE RESTRICT,
                  name TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  mime_type TEXT,
                  size_bytes INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'active',
                  version INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS files_account_parent_idx
                  ON files(account_id, parent_id, status, name);
                CREATE TABLE IF NOT EXISTS activity (
                  id TEXT PRIMARY KEY,
                  account_id TEXT NOT NULL,
                  action TEXT NOT NULL,
                  target_name TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM files WHERE account_id=?",
                (DEMO_ACCOUNT_ID,),
            ).fetchone()["count"]
            if not count:
                self._seed(connection)

    def _seed(self, connection: sqlite3.Connection) -> None:
        created = utc_now()
        records = [
            ("fld_research", None, "Research", "folder", None, 0),
            ("fld_media", None, "Media Library", "folder", None, 0),
            ("file_launch", None, "Knowledge Dump launch notes.md", "document", "text/markdown", 18_420),
            ("file_map", "fld_research", "Cluster topology.pdf", "document", "application/pdf", 2_830_114),
            ("file_reference", "fld_media", "workstation-reference.png", "image", "image/png", 4_202_912),
        ]
        connection.executemany(
            """
            INSERT INTO files (
              id,account_id,parent_id,name,kind,mime_type,size_bytes,status,version,created_at,updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)
            """,
            [(item[0], DEMO_ACCOUNT_ID, *item[1:], created, created) for item in records],
        )
        self._activity(connection, DEMO_ACCOUNT_ID, "workspace_seeded", "Knowledge Dump")

    def login(self, email: str, password: str) -> dict[str, Any] | None:
        if email.strip().lower() != DEMO_EMAIL or password != DEMO_PASSWORD:
            return None
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions(token,account_id,expires_at,created_at) VALUES (?, ?, ?, ?)",
                (token, DEMO_ACCOUNT_ID, expires_at, utc_now()),
            )
        return {"account": self.account(), "accessToken": token, "expiresAt": expires_at}

    def account(self) -> dict[str, str]:
        return {
            "id": DEMO_ACCOUNT_ID,
            "email": DEMO_EMAIL,
            "displayName": "Knowledge Operator",
            "plan": "Development",
        }

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE token=?",
                (token,),
            ).fetchone()
            if not row:
                return None
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                connection.execute("DELETE FROM sessions WHERE token=?", (token,))
                return None
        return self.account()

    def logout(self, token: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token=?", (token,))

    def list_files(
        self,
        *,
        parent_id: str | None,
        status: str = "active",
        search: str = "",
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM files WHERE account_id=? AND status=?"
        values: list[Any] = [DEMO_ACCOUNT_ID, status]
        if parent_id:
            query += " AND parent_id=?"
            values.append(parent_id)
        else:
            query += " AND parent_id IS NULL"
        if search.strip():
            query += " AND lower(name) LIKE ?"
            values.append(f"%{search.strip().lower()}%")
        query += " ORDER BY CASE WHEN kind='folder' THEN 0 ELSE 1 END, lower(name)"
        with self.connect() as connection:
            return [self._public_file(dict(item)) for item in connection.execute(query, values).fetchall()]

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM files WHERE id=? AND account_id=?",
                (file_id, DEMO_ACCOUNT_ID),
            ).fetchone()
        return self._public_file(dict(row)) if row else None

    def create_folder(self, name: str, parent_id: str | None) -> dict[str, Any]:
        return self._create(name=name, parent_id=parent_id, kind="folder", mime_type=None, size_bytes=0)

    def create_file(
        self,
        *,
        name: str,
        parent_id: str | None,
        kind: str,
        mime_type: str | None,
        size_bytes: int,
    ) -> dict[str, Any]:
        return self._create(
            name=name,
            parent_id=parent_id,
            kind=kind,
            mime_type=mime_type,
            size_bytes=max(0, size_bytes),
        )

    def _create(
        self,
        *,
        name: str,
        parent_id: str | None,
        kind: str,
        mime_type: str | None,
        size_bytes: int,
    ) -> dict[str, Any]:
        normalized_name = name.strip()[:240]
        if not normalized_name or "/" in normalized_name or "\\" in normalized_name:
            raise ValueError("file_name_invalid")
        if parent_id:
            parent = self.get_file(parent_id)
            if not parent or parent["kind"] != "folder":
                raise ValueError("parent_folder_not_found")
        file_id = f"obj_{uuid.uuid4().hex}"
        created = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO files (
                  id,account_id,parent_id,name,kind,mime_type,size_bytes,status,version,created_at,updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (file_id, DEMO_ACCOUNT_ID, parent_id, normalized_name, kind, mime_type, size_bytes, created, created),
            )
            self._activity(connection, DEMO_ACCOUNT_ID, "folder_created" if kind == "folder" else "file_uploaded", normalized_name)
        return self.get_file(file_id) or {}

    def update_file(self, file_id: str, *, name: str | None, parent_id: str | None | object) -> dict[str, Any] | None:
        existing = self.get_file(file_id)
        if not existing:
            return None
        updates: list[str] = []
        values: list[Any] = []
        if name is not None:
            normalized_name = name.strip()[:240]
            if not normalized_name or "/" in normalized_name or "\\" in normalized_name:
                raise ValueError("file_name_invalid")
            updates.append("name=?")
            values.append(normalized_name)
        if parent_id is not _UNSET:
            if parent_id:
                parent = self.get_file(str(parent_id))
                if not parent or parent["kind"] != "folder" or parent["id"] == file_id:
                    raise ValueError("parent_folder_not_found")
            updates.append("parent_id=?")
            values.append(parent_id)
        if not updates:
            return existing
        updates.extend(["version=version+1", "updated_at=?"])
        values.extend([utc_now(), file_id, DEMO_ACCOUNT_ID])
        with self.connect() as connection:
            connection.execute(
                f"UPDATE files SET {', '.join(updates)} WHERE id=? AND account_id=?",
                values,
            )
            self._activity(connection, DEMO_ACCOUNT_ID, "file_updated", str(name or existing["name"]))
        return self.get_file(file_id)

    def set_status(self, file_id: str, status: str) -> dict[str, Any] | None:
        existing = self.get_file(file_id)
        if not existing:
            return None
        with self.connect() as connection:
            connection.execute(
                "UPDATE files SET status=?, version=version+1, updated_at=? WHERE id=? AND account_id=?",
                (status, utc_now(), file_id, DEMO_ACCOUNT_ID),
            )
            self._activity(connection, DEMO_ACCOUNT_ID, f"file_{status}", existing["name"])
        return self.get_file(file_id)

    def purge(self, file_id: str) -> bool:
        existing = self.get_file(file_id)
        if not existing:
            return False
        with self.connect() as connection:
            children = connection.execute("SELECT COUNT(*) AS count FROM files WHERE parent_id=?", (file_id,)).fetchone()["count"]
            if children:
                raise ValueError("folder_not_empty")
            connection.execute("DELETE FROM files WHERE id=? AND account_id=?", (file_id, DEMO_ACCOUNT_ID))
            self._activity(connection, DEMO_ACCOUNT_ID, "file_deleted", existing["name"])
        return True

    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM activity WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
                (DEMO_ACCOUNT_ID, max(1, min(limit, 100))),
            ).fetchall()
        return [
            {"id": item["id"], "action": item["action"], "targetName": item["target_name"], "createdAt": item["created_at"]}
            for item in rows
        ]

    def usage(self) -> int:
        with self.connect() as connection:
            return int(connection.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS used FROM files WHERE account_id=? AND status='active'",
                (DEMO_ACCOUNT_ID,),
            ).fetchone()["used"])

    def _activity(self, connection: sqlite3.Connection, account_id: str, action: str, target_name: str) -> None:
        connection.execute(
            "INSERT INTO activity(id,account_id,action,target_name,created_at) VALUES (?, ?, ?, ?, ?)",
            (f"evt_{uuid.uuid4().hex}", account_id, action, target_name, utc_now()),
        )

    @staticmethod
    def _public_file(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item["id"],
            "parentId": item["parent_id"],
            "name": item["name"],
            "kind": item["kind"],
            "mimeType": item["mime_type"],
            "sizeBytes": item["size_bytes"],
            "status": item["status"],
            "version": item["version"],
            "createdAt": item["created_at"],
            "updatedAt": item["updated_at"],
        }


_UNSET = object()
