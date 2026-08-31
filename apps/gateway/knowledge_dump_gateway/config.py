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

        return cls(
            mode=mode,
            database_url=database_url,
            token_pepper=token_pepper,
            access_token_minutes=max(5, int(os.environ.get("KNOWLEDGE_DUMP_ACCESS_TOKEN_MINUTES", "15"))),
            refresh_token_days=max(1, int(os.environ.get("KNOWLEDGE_DUMP_REFRESH_TOKEN_DAYS", "30"))),
            default_quota_bytes=max(1, int(os.environ.get("KNOWLEDGE_DUMP_DEFAULT_QUOTA_BYTES", str(250 * 1024**3)))),
            default_quota_objects=max(1, int(os.environ.get("KNOWLEDGE_DUMP_DEFAULT_QUOTA_OBJECTS", "1000000"))),
            bootstrap_demo_account=_bool_env("KNOWLEDGE_DUMP_BOOTSTRAP_DEMO_ACCOUNT", mode == "development"),
            storage_provider=os.environ.get("KNOWLEDGE_DUMP_STORAGE_PROVIDER", "mock").strip().lower(),
        )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
