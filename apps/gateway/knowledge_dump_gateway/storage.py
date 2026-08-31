from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .paths import mock_objects_root


class StorageAdapter(Protocol):
    """Boundary implemented by local development and S3-compatible storage."""

    def health(self) -> bool: ...
    def write_placeholder(self, object_key: str, content: bytes) -> None: ...
    def read(self, object_key: str) -> bytes: ...
    def delete(self, object_key: str) -> None: ...


@dataclass(frozen=True)
class MockStorageAdapter:
    root: Path

    @classmethod
    def from_xdg(cls) -> "MockStorageAdapter":
        return cls(mock_objects_root())

    def _path(self, object_key: str) -> Path:
        safe_key = object_key.replace("/", "_")
        return self.root / safe_key

    def health(self) -> bool:
        return self.root.is_dir() and self.root.exists()

    def write_placeholder(self, object_key: str, content: bytes) -> None:
        self._path(object_key).write_bytes(content)

    def read(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()

    def delete(self, object_key: str) -> None:
        self._path(object_key).unlink(missing_ok=True)


class SpacesStorageAdapter:
    """Production adapter seam; SDK and presigned transfer work is phase two."""

    def __init__(self, *, endpoint: str, region: str, bucket: str) -> None:
        self.endpoint = endpoint
        self.region = region
        self.bucket = bucket

    def health(self) -> bool:
        raise NotImplementedError("DigitalOcean Spaces is not connected in the mock milestone")

    def write_placeholder(self, object_key: str, content: bytes) -> None:
        raise NotImplementedError

    def read(self, object_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError
