from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)

schema_versions = Table(
    "schema_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", String(40), nullable=False),
)

accounts = Table(
    "accounts",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("display_name", String(160), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("plan", String(40), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

quotas = Table(
    "account_quotas",
    metadata,
    Column("account_id", String(80), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("max_bytes", BigInteger, nullable=False),
    Column("max_objects", BigInteger, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

devices = Table(
    "devices",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("account_id", String(80), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("label", String(160), nullable=False),
    Column("platform", String(80), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("last_seen_at", String(40), nullable=False),
    Column("revoked_at", String(40)),
)
Index("ix_devices_account_status", devices.c.account_id, devices.c.status)

sessions = Table(
    "sessions",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("account_id", String(80), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("device_id", String(80), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
    Column("access_token_hash", String(64), nullable=False, unique=True),
    Column("refresh_token_hash", String(64), nullable=False, unique=True),
    Column("access_expires_at", String(40), nullable=False),
    Column("refresh_expires_at", String(40), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("last_used_at", String(40), nullable=False),
    Column("revoked_at", String(40)),
)
Index("ix_sessions_account_active", sessions.c.account_id, sessions.c.revoked_at)

files = Table(
    "files",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("account_id", String(80), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("parent_id", String(80), ForeignKey("files.id", ondelete="RESTRICT")),
    Column("name", String(240), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("mime_type", String(255)),
    Column("size_bytes", BigInteger, nullable=False),
    Column("status", String(32), nullable=False),
    Column("version", Integer, nullable=False),
    Column("object_key", String(500)),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
Index("ix_files_account_parent_status", files.c.account_id, files.c.parent_id, files.c.status)

file_versions = Table(
    "file_versions",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("file_id", String(80), ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
    Column("account_id", String(80), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("object_key", String(500)),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("file_id", "version", name="uq_file_versions_file_version"),
)
Index("ix_file_versions_account_file", file_versions.c.account_id, file_versions.c.file_id)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("account_id", String(80), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("actor_device_id", String(80), ForeignKey("devices.id", ondelete="SET NULL")),
    Column("action", String(80), nullable=False),
    Column("target_type", String(50), nullable=False),
    Column("target_id", String(80)),
    Column("target_name", String(240), nullable=False),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
)
Index("ix_audit_account_created", audit_events.c.account_id, audit_events.c.created_at)


SCHEMA_VERSION = 2
