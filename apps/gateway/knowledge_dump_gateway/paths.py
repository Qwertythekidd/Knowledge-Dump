from __future__ import annotations

import os
from pathlib import Path


def _xdg_root(variable: str, fallback: str) -> Path:
    configured = os.environ.get(variable, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / fallback).resolve()


def data_root() -> Path:
    override = os.environ.get("KNOWLEDGE_DUMP_DATA_HOME", "").strip()
    root = Path(override).expanduser().resolve() if override else _xdg_root("XDG_DATA_HOME", ".local/share") / "knowledge-dump"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def state_root() -> Path:
    root = _xdg_root("XDG_STATE_HOME", ".local/state") / "knowledge-dump"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def catalog_path() -> Path:
    return data_root() / "catalog.db"


def mock_objects_root() -> Path:
    root = data_root() / "mock-objects"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root
