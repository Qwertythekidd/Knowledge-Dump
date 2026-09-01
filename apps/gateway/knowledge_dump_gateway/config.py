from __future__ import annotations

import os
from dataclasses import dataclass

from .paths import catalog_path


@dataclass(frozen=True)
class GatewayConfig:
    mode: str
    database_url: str
    token_pepper: str
    access_token_minutes: int
    refresh_token_days: int
    default_quota_bytes: int
    default_quota_objects: int
    bootstrap_demo_account: bool
    storage_provider: str
    storage_endpoint: str
    storage_region: str
    storage_bucket: str
    storage_access_key_id: str
    storage_secret_access_key: str
    transfer_url_seconds: int
    upload_session_hours: int
    multipart_part_bytes: int

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        mode = os.environ.get("KNOWLEDGE_DUMP_MODE", "development").strip().lower()
        if mode not in {"development", "production", "test"}:
            raise RuntimeError("knowledge_dump_mode_invalid")

        database_url = os.environ.get("KNOWLEDGE_DUMP_DATABASE_URL", "").strip()
        if not database_url:
            database_url = f"sqlite+pysqlite:///{catalog_path()}"

        token_pepper = os.environ.get("KNOWLEDGE_DUMP_TOKEN_PEPPER", "").strip()
        if not token_pepper and mode == "production":
            raise RuntimeError("knowledge_dump_token_pepper_required")
        if not token_pepper:
            token_pepper = "knowledge-dump-development-token-pepper"

        storage_provider = os.environ.get("KNOWLEDGE_DUMP_STORAGE_PROVIDER", "mock").strip().lower()
        if storage_provider not in {"mock", "digitalocean_spaces", "s3_compatible"}:
            raise RuntimeError("knowledge_dump_storage_provider_invalid")
        storage_endpoint = os.environ.get("KNOWLEDGE_DUMP_SPACES_ENDPOINT", "").strip().rstrip("/")
        storage_region = os.environ.get("KNOWLEDGE_DUMP_SPACES_REGION", "").strip()
        storage_bucket = os.environ.get("KNOWLEDGE_DUMP_SPACES_BUCKET", "").strip()
        storage_access_key_id = os.environ.get("KNOWLEDGE_DUMP_SPACES_ACCESS_KEY_ID", "").strip()
        storage_secret_access_key = os.environ.get("KNOWLEDGE_DUMP_SPACES_SECRET_ACCESS_KEY", "").strip()
        if storage_provider != "mock" and not all((
            storage_endpoint,
            storage_region,
            storage_bucket,
            storage_access_key_id,
            storage_secret_access_key,
        )):
            raise RuntimeError("knowledge_dump_storage_credentials_required")

        return cls(
            mode=mode,
            database_url=database_url,
            token_pepper=token_pepper,
            access_token_minutes=max(5, int(os.environ.get("KNOWLEDGE_DUMP_ACCESS_TOKEN_MINUTES", "15"))),
            refresh_token_days=max(1, int(os.environ.get("KNOWLEDGE_DUMP_REFRESH_TOKEN_DAYS", "30"))),
            default_quota_bytes=max(1, int(os.environ.get("KNOWLEDGE_DUMP_DEFAULT_QUOTA_BYTES", str(250 * 1024**3)))),
            default_quota_objects=max(1, int(os.environ.get("KNOWLEDGE_DUMP_DEFAULT_QUOTA_OBJECTS", "1000000"))),
            bootstrap_demo_account=_bool_env("KNOWLEDGE_DUMP_BOOTSTRAP_DEMO_ACCOUNT", mode == "development"),
            storage_provider=storage_provider,
            storage_endpoint=storage_endpoint,
            storage_region=storage_region,
            storage_bucket=storage_bucket,
            storage_access_key_id=storage_access_key_id,
            storage_secret_access_key=storage_secret_access_key,
            transfer_url_seconds=max(60, min(3600, int(os.environ.get("KNOWLEDGE_DUMP_TRANSFER_URL_SECONDS", "900")))),
            upload_session_hours=max(1, min(48, int(os.environ.get("KNOWLEDGE_DUMP_UPLOAD_SESSION_HOURS", "24")))),
            multipart_part_bytes=max(5 * 1024**2, int(os.environ.get("KNOWLEDGE_DUMP_MULTIPART_PART_BYTES", str(8 * 1024**2)))),
        )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
