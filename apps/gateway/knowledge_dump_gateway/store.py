from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, create_engine, delete, event, func, inspect, insert, or_, select, update
from sqlalchemy.engine import Connection, Engine

from .config import GatewayConfig
from .schema import (
    SCHEMA_VERSION,
    accounts,
    audit_events,
    devices,
    file_versions,
    files,
    metadata,
    quotas,
    schema_versions,
    sessions,
)
from .security import CredentialSecurity


DEMO_EMAIL = "demo@knowledge-dump.local"
DEMO_PASSWORD = "knowledge-dump"
DEMO_ACCOUNT_ID = "acct_demo"
_UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(*, minutes: int = 0, days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes, days=days)).isoformat()


def _expired(value: str) -> bool:
    return datetime.fromisoformat(value) <= datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuthContext:
    account_id: str
    device_id: str
    session_id: str
    account: dict[str, Any]
    device: dict[str, Any]


class Catalog:
    def __init__(
        self,
        path: Path | None = None,
        *,
        config: GatewayConfig | None = None,
        bootstrap_demo: bool | None = None,
    ) -> None:
        resolved = config or GatewayConfig.from_env()
        if path is not None:
            resolved = replace(
                resolved,
                mode="test",
                database_url=f"sqlite+pysqlite:///{path.resolve()}",
                bootstrap_demo_account=True if bootstrap_demo is None else bootstrap_demo,
            )
        elif bootstrap_demo is not None:
            resolved = replace(resolved, bootstrap_demo_account=bootstrap_demo)
        self.config = resolved
        self.security = CredentialSecurity(resolved.token_pepper)
        self.engine = self._create_engine(resolved.database_url)
        self._initialize()

    @staticmethod
    def _create_engine(database_url: str) -> Engine:
        options: dict[str, Any] = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        engine = create_engine(database_url, **options)
        if engine.dialect.name == "sqlite":
            @event.listens_for(engine, "connect")
            def set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
        return engine

    @property
    def database_backend(self) -> str:
        return self.engine.dialect.name

    def _initialize(self) -> None:
        self._preserve_legacy_sqlite_schema()
        metadata.create_all(self.engine)
        now = utc_now()
        with self.engine.begin() as connection:
            known = connection.execute(
                select(schema_versions.c.version).where(schema_versions.c.version == SCHEMA_VERSION)
            ).scalar_one_or_none()
            if known is None:
                connection.execute(insert(schema_versions).values(version=SCHEMA_VERSION, applied_at=now))
        if self.config.bootstrap_demo_account and not self.account_by_email(DEMO_EMAIL):
            self.create_account(
                email=DEMO_EMAIL,
                password=DEMO_PASSWORD,
                display_name="Knowledge Operator",
                plan="Development",
                account_id=DEMO_ACCOUNT_ID,
                seed_workspace=True,
            )

    def _preserve_legacy_sqlite_schema(self) -> None:
        if self.engine.dialect.name != "sqlite":
            return
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        if "files" not in tables or "accounts" in tables:
            return
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            for table_name in ("sessions", "files", "activity"):
                if table_name in tables:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table_name}" RENAME TO "legacy_{table_name}_{suffix}"'
                    )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    def create_account(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        plan: str = "Personal",
        quota_bytes: int | None = None,
        quota_objects: int | None = None,
        account_id: str | None = None,
        seed_workspace: bool = False,
    ) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        normalized_name = display_name.strip()
        if not normalized_email or "@" not in normalized_email or len(normalized_email) > 320:
            raise ValueError("email_invalid")
        if not normalized_name or len(normalized_name) > 160:
            raise ValueError("display_name_invalid")
        password_hash = self.security.hash_password(password)
        identifier = account_id or f"acct_{uuid.uuid4().hex}"
        now = utc_now()
        with self.engine.begin() as connection:
            if connection.execute(select(accounts.c.id).where(accounts.c.email == normalized_email)).scalar_one_or_none():
                raise ValueError("account_email_exists")
            connection.execute(insert(accounts).values(
                id=identifier,
                email=normalized_email,
                display_name=normalized_name,
                password_hash=password_hash,
                plan=plan.strip()[:40] or "Personal",
                status="active",
                created_at=now,
                updated_at=now,
            ))
            connection.execute(insert(quotas).values(
                account_id=identifier,
                max_bytes=quota_bytes or self.config.default_quota_bytes,
                max_objects=quota_objects or self.config.default_quota_objects,
                created_at=now,
                updated_at=now,
            ))
            self._audit(connection, identifier, None, "account_created", "account", identifier, normalized_name)
            if seed_workspace:
                self._seed_workspace(connection, identifier)
        return self.account(identifier) or {}

    def account(self, account_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(accounts).where(accounts.c.id == account_id)
            ).mappings().first()
        return self._public_account(row) if row else None

    def account_by_email(self, email: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(accounts).where(accounts.c.email == email.strip().lower())
            ).mappings().first()
        return self._public_account(row) if row else None

    def login(
        self,
        email: str,
        password: str,
        *,
        requested_device_id: str | None = None,
        device_label: str = "Knowledge Dump workstation",
        platform: str = "unknown",
    ) -> dict[str, Any] | None:
        normalized_email = email.strip().lower()
        with self.engine.begin() as connection:
            account_row = connection.execute(
                select(accounts).where(accounts.c.email == normalized_email)
            ).mappings().first()
            if not account_row or account_row["status"] != "active":
                return None
            verified, replacement = self.security.verify_password(account_row["password_hash"], password)
            if not verified:
                return None
            if replacement:
                connection.execute(update(accounts).where(accounts.c.id == account_row["id"]).values(
                    password_hash=replacement,
                    updated_at=utc_now(),
                ))
            device_row = self._resolve_device(
                connection,
                account_row["id"],
                requested_device_id,
                device_label,
                platform,
            )
            access_token = self.security.new_token()
            refresh_token = self.security.new_token()
            session_id = f"ses_{uuid.uuid4().hex}"
            now = utc_now()
            access_expires = _future(minutes=self.config.access_token_minutes)
            refresh_expires = _future(days=self.config.refresh_token_days)
            connection.execute(insert(sessions).values(
                id=session_id,
                account_id=account_row["id"],
                device_id=device_row["id"],
                access_token_hash=self.security.token_hash(access_token),
                refresh_token_hash=self.security.token_hash(refresh_token),
                access_expires_at=access_expires,
                refresh_expires_at=refresh_expires,
                created_at=now,
                last_used_at=now,
                revoked_at=None,
            ))
            self._audit(
                connection,
                account_row["id"],
                device_row["id"],
                "session_created",
                "session",
                session_id,
                device_row["label"],
            )
            return self._session_payload(
                account_row,
                device_row,
                access_token,
                refresh_token,
                access_expires,
                refresh_expires,
            )

    def authenticate(self, access_token: str) -> AuthContext | None:
        if not access_token:
            return None
        token_hash = self.security.token_hash(access_token)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(
                    sessions,
                    accounts.c.email,
                    accounts.c.display_name,
                    accounts.c.plan,
                    accounts.c.status.label("account_status"),
                    accounts.c.created_at.label("account_created_at"),
                    devices.c.label.label("device_label"),
                    devices.c.platform.label("device_platform"),
                    devices.c.status.label("device_status"),
                    devices.c.created_at.label("device_created_at"),
                    devices.c.last_seen_at.label("device_last_seen_at"),
                    devices.c.revoked_at.label("device_revoked_at"),
                )
                .join(accounts, accounts.c.id == sessions.c.account_id)
                .join(devices, devices.c.id == sessions.c.device_id)
                .where(sessions.c.access_token_hash == token_hash)
            ).mappings().first()
            if not row or row["revoked_at"] or row["account_status"] != "active" or row["device_status"] != "active":
                return None
            if _expired(row["access_expires_at"]):
                return None
            now = utc_now()
            connection.execute(update(sessions).where(sessions.c.id == row["id"]).values(last_used_at=now))
            connection.execute(update(devices).where(devices.c.id == row["device_id"]).values(last_seen_at=now))
            return AuthContext(
                account_id=row["account_id"],
                device_id=row["device_id"],
                session_id=row["id"],
                account={
                    "id": row["account_id"],
                    "email": row["email"],
                    "displayName": row["display_name"],
                    "plan": row["plan"],
                    "status": row["account_status"],
                    "createdAt": row["account_created_at"],
                },
                device={
                    "id": row["device_id"],
                    "label": row["device_label"],
                    "platform": row["device_platform"],
                    "status": row["device_status"],
                    "createdAt": row["device_created_at"],
                    "lastSeenAt": now,
                    "revokedAt": row["device_revoked_at"],
                },
            )

    def refresh(self, refresh_token: str) -> dict[str, Any] | None:
        if not refresh_token:
            return None
        token_hash = self.security.token_hash(refresh_token)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(
                    sessions,
                    accounts.c.email,
                    accounts.c.display_name,
                    accounts.c.plan,
                    accounts.c.status.label("account_status"),
                    accounts.c.created_at.label("account_created_at"),
                    devices.c.label.label("device_label"),
                    devices.c.platform.label("device_platform"),
                    devices.c.status.label("device_status"),
                    devices.c.created_at.label("device_created_at"),
                    devices.c.last_seen_at.label("device_last_seen_at"),
                    devices.c.revoked_at.label("device_revoked_at"),
                )
                .join(accounts, accounts.c.id == sessions.c.account_id)
                .join(devices, devices.c.id == sessions.c.device_id)
                .where(sessions.c.refresh_token_hash == token_hash)
            ).mappings().first()
            if not row or row["revoked_at"] or row["account_status"] != "active" or row["device_status"] != "active":
                return None
            if _expired(row["refresh_expires_at"]):
                connection.execute(update(sessions).where(sessions.c.id == row["id"]).values(revoked_at=utc_now()))
                return None
            access_token = self.security.new_token()
            next_refresh_token = self.security.new_token()
            now = utc_now()
            access_expires = _future(minutes=self.config.access_token_minutes)
            refresh_expires = _future(days=self.config.refresh_token_days)
            connection.execute(update(sessions).where(sessions.c.id == row["id"]).values(
                access_token_hash=self.security.token_hash(access_token),
                refresh_token_hash=self.security.token_hash(next_refresh_token),
                access_expires_at=access_expires,
                refresh_expires_at=refresh_expires,
                last_used_at=now,
            ))
            connection.execute(update(devices).where(devices.c.id == row["device_id"]).values(last_seen_at=now))
            account_row = {
                "id": row["account_id"],
                "email": row["email"],
                "display_name": row["display_name"],
                "plan": row["plan"],
                "status": row["account_status"],
                "created_at": row["account_created_at"],
            }
            device_row = {
                "id": row["device_id"],
                "label": row["device_label"],
                "platform": row["device_platform"],
                "status": row["device_status"],
                "created_at": row["device_created_at"],
                "last_seen_at": now,
                "revoked_at": row["device_revoked_at"],
            }
            return self._session_payload(
                account_row,
                device_row,
                access_token,
                next_refresh_token,
                access_expires,
                refresh_expires,
            )

    def logout(self, access_token: str) -> None:
        if not access_token:
            return
        with self.engine.begin() as connection:
            connection.execute(
                update(sessions)
                .where(and_(sessions.c.access_token_hash == self.security.token_hash(access_token), sessions.c.revoked_at.is_(None)))
                .values(revoked_at=utc_now())
            )

    def list_devices(self, account_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(devices).where(devices.c.account_id == account_id).order_by(devices.c.last_seen_at.desc())
            ).mappings().all()
        return [self._public_device(row) for row in rows]

    def revoke_device(self, account_id: str, device_id: str, actor_device_id: str) -> bool:
        now = utc_now()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(devices).where(and_(devices.c.id == device_id, devices.c.account_id == account_id))
            ).mappings().first()
            if not row:
                return False
            connection.execute(update(devices).where(devices.c.id == device_id).values(status="revoked", revoked_at=now))
            connection.execute(update(sessions).where(and_(sessions.c.device_id == device_id, sessions.c.revoked_at.is_(None))).values(revoked_at=now))
            self._audit(connection, account_id, actor_device_id, "device_revoked", "device", device_id, row["label"])
        return True

    def quota(self, account_id: str) -> dict[str, int]:
        with self.engine.connect() as connection:
            row = connection.execute(select(quotas).where(quotas.c.account_id == account_id)).mappings().one()
            usage = self._usage(connection, account_id)
        return {
            "maxBytes": int(row["max_bytes"]),
            "maxObjects": int(row["max_objects"]),
            "usedBytes": usage["bytes"],
            "usedObjects": usage["objects"],
        }

    def list_files(self, account_id: str, *, parent_id: str | None, status: str = "active", search: str = "") -> list[dict[str, Any]]:
        if status not in {"active", "archived"}:
            raise ValueError("file_status_invalid")
        statement = select(files).where(and_(files.c.account_id == account_id, files.c.status == status))
        statement = statement.where(files.c.parent_id == parent_id) if parent_id else statement.where(files.c.parent_id.is_(None))
        if search.strip():
            statement = statement.where(func.lower(files.c.name).like(f"%{search.strip().lower()}%"))
        statement = statement.order_by(files.c.kind != "folder", func.lower(files.c.name))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._public_file(row) for row in rows]

    def get_file(self, account_id: str, file_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(files).where(and_(files.c.id == file_id, files.c.account_id == account_id))
            ).mappings().first()
        return self._public_file(row) if row else None

    def list_versions(self, account_id: str, file_id: str) -> list[dict[str, Any]] | None:
        if not self.get_file(account_id, file_id):
            return None
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(file_versions)
                .where(and_(file_versions.c.account_id == account_id, file_versions.c.file_id == file_id))
                .order_by(file_versions.c.version.desc())
            ).mappings().all()
        return [{
            "id": row["id"],
            "fileId": row["file_id"],
            "version": row["version"],
            "sizeBytes": row["size_bytes"],
            "objectKey": row["object_key"],
            "metadata": json.loads(row["metadata_json"]),
            "createdAt": row["created_at"],
        } for row in rows]

    def create_folder(self, account_id: str, name: str, parent_id: str | None, actor_device_id: str) -> dict[str, Any]:
        return self._create(account_id, name=name, parent_id=parent_id, kind="folder", mime_type=None, size_bytes=0, actor_device_id=actor_device_id)

    def create_file(
        self,
        account_id: str,
        *,
        name: str,
        parent_id: str | None,
        kind: str,
        mime_type: str | None,
        size_bytes: int,
        actor_device_id: str,
    ) -> dict[str, Any]:
        if kind == "folder":
            raise ValueError("file_kind_invalid")
        return self._create(
            account_id,
            name=name,
            parent_id=parent_id,
            kind=kind,
            mime_type=mime_type,
            size_bytes=max(0, size_bytes),
            actor_device_id=actor_device_id,
        )

    def _create(
        self,
        account_id: str,
        *,
        name: str,
        parent_id: str | None,
        kind: str,
        mime_type: str | None,
        size_bytes: int,
        actor_device_id: str,
    ) -> dict[str, Any]:
        normalized_name = self._valid_name(name)
        identifier = f"obj_{uuid.uuid4().hex}"
        now = utc_now()
        with self.engine.begin() as connection:
            self._validate_parent(connection, account_id, parent_id, identifier)
            if kind != "folder":
                self._enforce_quota(connection, account_id, size_bytes)
            connection.execute(insert(files).values(
                id=identifier,
                account_id=account_id,
                parent_id=parent_id,
                name=normalized_name,
                kind=kind,
                mime_type=mime_type,
                size_bytes=size_bytes,
                status="active",
                version=1,
                object_key=None,
                created_at=now,
                updated_at=now,
            ))
            row = connection.execute(select(files).where(files.c.id == identifier)).mappings().one()
            self._snapshot_version(connection, row)
            self._audit(
                connection,
                account_id,
                actor_device_id,
                "folder_created" if kind == "folder" else "file_uploaded",
                kind,
                identifier,
                normalized_name,
            )
        return self.get_file(account_id, identifier) or {}

    def update_file(
        self,
        account_id: str,
        file_id: str,
        *,
        name: str | None,
        parent_id: str | None | object,
        actor_device_id: str,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(files).where(and_(files.c.id == file_id, files.c.account_id == account_id))
            ).mappings().first()
            if not existing:
                return None
            values: dict[str, Any] = {"version": existing["version"] + 1, "updated_at": now}
            if name is not None:
                values["name"] = self._valid_name(name)
            if parent_id is not _UNSET:
                self._validate_parent(connection, account_id, parent_id, file_id)
                values["parent_id"] = parent_id
            connection.execute(update(files).where(files.c.id == file_id).values(**values))
            row = connection.execute(select(files).where(files.c.id == file_id)).mappings().one()
            self._snapshot_version(connection, row)
            self._audit(connection, account_id, actor_device_id, "file_updated", existing["kind"], file_id, values.get("name", existing["name"]))
        return self.get_file(account_id, file_id)

    def set_status(self, account_id: str, file_id: str, status: str, actor_device_id: str) -> dict[str, Any] | None:
        if status not in {"active", "archived"}:
            raise ValueError("file_status_invalid")
        now = utc_now()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(files).where(and_(files.c.id == file_id, files.c.account_id == account_id))
            ).mappings().first()
            if not existing:
                return None
            connection.execute(update(files).where(files.c.id == file_id).values(
                status=status,
                version=existing["version"] + 1,
                updated_at=now,
            ))
            row = connection.execute(select(files).where(files.c.id == file_id)).mappings().one()
            self._snapshot_version(connection, row)
            self._audit(connection, account_id, actor_device_id, f"file_{status}", existing["kind"], file_id, existing["name"])
        return self.get_file(account_id, file_id)

    def purge(self, account_id: str, file_id: str, actor_device_id: str) -> bool:
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(files).where(and_(files.c.id == file_id, files.c.account_id == account_id))
            ).mappings().first()
            if not existing:
                return False
            child_count = connection.execute(
                select(func.count()).select_from(files).where(and_(files.c.parent_id == file_id, files.c.account_id == account_id))
            ).scalar_one()
            if child_count:
                raise ValueError("folder_not_empty")
            connection.execute(delete(files).where(and_(files.c.id == file_id, files.c.account_id == account_id)))
            self._audit(connection, account_id, actor_device_id, "file_deleted", existing["kind"], file_id, existing["name"])
        return True

    def list_activity(self, account_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(audit_events)
                .where(audit_events.c.account_id == account_id)
                .order_by(audit_events.c.created_at.desc())
                .limit(max(1, min(limit, 100)))
            ).mappings().all()
        return [{
            "id": row["id"],
            "action": row["action"],
            "targetName": row["target_name"],
            "targetType": row["target_type"],
            "targetId": row["target_id"],
            "actorDeviceId": row["actor_device_id"],
            "metadata": json.loads(row["metadata_json"]),
            "createdAt": row["created_at"],
        } for row in rows]

    def _resolve_device(
        self,
        connection: Connection,
        account_id: str,
        requested_device_id: str | None,
        label: str,
        platform: str,
    ) -> dict[str, Any]:
        if requested_device_id:
            existing = connection.execute(
                select(devices).where(and_(devices.c.id == requested_device_id, devices.c.account_id == account_id))
            ).mappings().first()
            if existing:
                if existing["status"] != "active":
                    raise ValueError("device_revoked")
                now = utc_now()
                connection.execute(update(devices).where(devices.c.id == requested_device_id).values(
                    label=label.strip()[:160] or existing["label"],
                    platform=platform.strip()[:80] or existing["platform"],
                    last_seen_at=now,
                ))
                return dict(connection.execute(select(devices).where(devices.c.id == requested_device_id)).mappings().one())
        identifier = f"dev_{uuid.uuid4().hex}"
        now = utc_now()
        connection.execute(insert(devices).values(
            id=identifier,
            account_id=account_id,
            label=label.strip()[:160] or "Knowledge Dump workstation",
            platform=platform.strip()[:80] or "unknown",
            status="active",
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
        ))
        return dict(connection.execute(select(devices).where(devices.c.id == identifier)).mappings().one())

    def _enforce_quota(self, connection: Connection, account_id: str, added_bytes: int) -> None:
        quota_row = connection.execute(
            select(quotas).where(quotas.c.account_id == account_id).with_for_update()
        ).mappings().one()
        usage = self._usage(connection, account_id)
        if usage["bytes"] + added_bytes > int(quota_row["max_bytes"]):
            raise ValueError("quota_bytes_exceeded")
        if usage["objects"] + 1 > int(quota_row["max_objects"]):
            raise ValueError("quota_objects_exceeded")

    @staticmethod
    def _usage(connection: Connection, account_id: str) -> dict[str, int]:
        row = connection.execute(
            select(
                func.coalesce(func.sum(files.c.size_bytes), 0).label("used_bytes"),
                func.count(files.c.id).label("used_objects"),
            ).where(and_(files.c.account_id == account_id, files.c.kind != "folder"))
        ).mappings().one()
        return {"bytes": int(row["used_bytes"]), "objects": int(row["used_objects"])}

    @staticmethod
    def _validate_parent(connection: Connection, account_id: str, parent_id: str | None | object, file_id: str) -> None:
        if not parent_id:
            return
        cursor = str(parent_id)
        visited: set[str] = set()
        while cursor:
            if cursor == file_id or cursor in visited:
                raise ValueError("folder_cycle_not_allowed")
            visited.add(cursor)
            parent = connection.execute(
                select(files.c.kind, files.c.parent_id, files.c.status).where(
                    and_(files.c.id == cursor, files.c.account_id == account_id)
                )
            ).mappings().first()
            if not parent or parent["kind"] != "folder" or parent["status"] != "active":
                raise ValueError("parent_folder_not_found")
            cursor = parent["parent_id"] or ""

    @staticmethod
    def _valid_name(name: str) -> str:
        normalized = name.strip()[:240]
        if not normalized or "/" in normalized or "\\" in normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("file_name_invalid")
        return normalized

    def _seed_workspace(self, connection: Connection, account_id: str) -> None:
        now = utc_now()
        records = [
            (f"obj_{uuid.uuid4().hex}", None, "Research", "folder", None, 0),
            (f"obj_{uuid.uuid4().hex}", None, "Media Library", "folder", None, 0),
            (f"obj_{uuid.uuid4().hex}", None, "Knowledge Dump launch notes.md", "document", "text/markdown", 18_420),
        ]
        for identifier, parent_id, name, kind, mime_type, size_bytes in records:
            connection.execute(insert(files).values(
                id=identifier,
                account_id=account_id,
                parent_id=parent_id,
                name=name,
                kind=kind,
                mime_type=mime_type,
                size_bytes=size_bytes,
                status="active",
                version=1,
                object_key=None,
                created_at=now,
                updated_at=now,
            ))
            row = connection.execute(select(files).where(files.c.id == identifier)).mappings().one()
            self._snapshot_version(connection, row)
        self._audit(connection, account_id, None, "workspace_seeded", "workspace", account_id, "Knowledge Dump")

    @staticmethod
    def _snapshot_version(connection: Connection, row: Any) -> None:
        connection.execute(insert(file_versions).values(
            id=f"ver_{uuid.uuid4().hex}",
            file_id=row["id"],
            account_id=row["account_id"],
            version=row["version"],
            size_bytes=row["size_bytes"],
            object_key=row["object_key"],
            metadata_json=json.dumps({
                "name": row["name"],
                "parentId": row["parent_id"],
                "kind": row["kind"],
                "mimeType": row["mime_type"],
                "status": row["status"],
            }, separators=(",", ":")),
            created_at=utc_now(),
        ))

    @staticmethod
    def _audit(
        connection: Connection,
        account_id: str,
        actor_device_id: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        target_name: str,
        metadata_value: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(insert(audit_events).values(
            id=f"evt_{uuid.uuid4().hex}",
            account_id=account_id,
            actor_device_id=actor_device_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name[:240],
            metadata_json=json.dumps(metadata_value or {}, separators=(",", ":")),
            created_at=utc_now(),
        ))

    @staticmethod
    def _public_account(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "email": row["email"],
            "displayName": row["display_name"],
            "plan": row["plan"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _public_device(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "label": row["label"],
            "platform": row["platform"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "lastSeenAt": row["last_seen_at"],
            "revokedAt": row["revoked_at"],
        }

    @staticmethod
    def _public_file(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "parentId": row["parent_id"],
            "name": row["name"],
            "kind": row["kind"],
            "mimeType": row["mime_type"],
            "sizeBytes": row["size_bytes"],
            "status": row["status"],
            "version": row["version"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _session_payload(
        self,
        account_row: Any,
        device_row: Any,
        access_token: str,
        refresh_token: str,
        access_expires: str,
        refresh_expires: str,
    ) -> dict[str, Any]:
        return {
            "account": self._public_account(account_row),
            "device": self._public_device(device_row),
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": access_expires,
            "refreshExpiresAt": refresh_expires,
        }
