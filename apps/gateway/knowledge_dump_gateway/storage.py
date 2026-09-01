from __future__ import annotations

import hashlib
import math
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .config import GatewayConfig
from .paths import mock_objects_root


MAX_MULTIPART_PART_BYTES = 5 * 1024**3
MAX_OBJECT_BYTES = 5 * 1024**4

@dataclass(frozen=True)
class StoredObject:
    object_key: str
    size_bytes: int
    etag: str


class StorageAdapter(Protocol):
    provider: str

    def health(self) -> bool: ...
    def create_multipart_upload(self, object_key: str, content_type: str | None) -> str: ...
    def presign_upload_part(self, object_key: str, upload_id: str, part_number: int, expires_in: int) -> str: ...
    def complete_multipart_upload(self, object_key: str, upload_id: str, parts: list[dict[str, Any]]) -> StoredObject: ...
    def abort_multipart_upload(self, object_key: str, upload_id: str) -> None: ...
    def head(self, object_key: str) -> StoredObject: ...
    def presign_download(self, object_key: str, file_name: str, content_type: str | None, expires_in: int) -> str: ...
    def delete(self, object_key: str) -> None: ...


@dataclass(frozen=True)
class MockStorageAdapter:
    root: Path
    provider: str = "mock"

    @classmethod
    def from_xdg(cls) -> "MockStorageAdapter":
        return cls(mock_objects_root())

    def _object_path(self, object_key: str) -> Path:
        parts = PurePosixPath(object_key).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("object_key_invalid")
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _upload_root(self, upload_id: str) -> Path:
        if not upload_id.startswith("mock_") or not upload_id[5:].isalnum():
            raise ValueError("provider_upload_id_invalid")
        path = self.root / "multipart" / upload_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def health(self) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.root / ".health"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return True

    def create_multipart_upload(self, object_key: str, content_type: str | None) -> str:
        del object_key, content_type
        upload_id = f"mock_{uuid.uuid4().hex}"
        self._upload_root(upload_id)
        return upload_id

    def presign_upload_part(self, object_key: str, upload_id: str, part_number: int, expires_in: int) -> str:
        del object_key, upload_id, part_number, expires_in
        raise RuntimeError("mock_upload_urls_are_gateway_issued")

    def put_part(self, upload_id: str, part_number: int, content: bytes) -> str:
        if part_number < 1 or part_number > 10_000:
            raise ValueError("upload_part_number_invalid")
        etag = hashlib.md5(content, usedforsecurity=False).hexdigest()
        (self._upload_root(upload_id) / f"part-{part_number:05d}").write_bytes(content)
        return f'"{etag}"'

    def complete_multipart_upload(self, object_key: str, upload_id: str, parts: list[dict[str, Any]]) -> StoredObject:
        destination = self._object_path(object_key)
        temporary = destination.with_suffix(f".assembling-{uuid.uuid4().hex}")
        upload_root = self._upload_root(upload_id)
        digest = hashlib.md5(usedforsecurity=False)
        size = 0
        try:
            with temporary.open("wb") as output:
                for part in sorted(parts, key=lambda item: int(item["PartNumber"])):
                    content = (upload_root / f"part-{int(part['PartNumber']):05d}").read_bytes()
                    digest.update(content)
                    size += len(content)
                    output.write(content)
            temporary.replace(destination)
            shutil.rmtree(upload_root, ignore_errors=True)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObject(object_key=object_key, size_bytes=size, etag=f'"{digest.hexdigest()}"')

    def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        del object_key
        shutil.rmtree(self._upload_root(upload_id), ignore_errors=True)

    def head(self, object_key: str) -> StoredObject:
        path = self._object_path(object_key)
        if not path.is_file():
            raise FileNotFoundError(object_key)
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return StoredObject(
            object_key=object_key,
            size_bytes=path.stat().st_size,
            etag=f'"{digest.hexdigest()}"',
        )

    def presign_download(self, object_key: str, file_name: str, content_type: str | None, expires_in: int) -> str:
        del object_key, file_name, content_type, expires_in
        raise RuntimeError("mock_download_urls_are_gateway_issued")

    def read(self, object_key: str, start: int | None = None, end: int | None = None) -> bytes:
        path = self._object_path(object_key)
        with path.open("rb") as source:
            if start is not None:
                source.seek(start)
            return source.read(None if end is None else end - (start or 0) + 1)

    def delete(self, object_key: str) -> None:
        self._object_path(object_key).unlink(missing_ok=True)


class SpacesStorageAdapter:
    provider = "digitalocean_spaces"

    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        bucket: str,
        access_key_id: str = "",
        secret_access_key: str = "",
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.region = region
        self.bucket = bucket
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.session.Session().client(
                "s3",
                region_name=region,
                endpoint_url=self.endpoint,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
            )
        self.client = client

    def health(self) -> bool:
        self.client.head_bucket(Bucket=self.bucket)
        return True

    def create_multipart_upload(self, object_key: str, content_type: str | None) -> str:
        parameters: dict[str, Any] = {"Bucket": self.bucket, "Key": object_key, "ACL": "private"}
        if content_type:
            parameters["ContentType"] = content_type
        return str(self.client.create_multipart_upload(**parameters)["UploadId"])

    def presign_upload_part(self, object_key: str, upload_id: str, part_number: int, expires_in: int) -> str:
        return str(self.client.generate_presigned_url(
            ClientMethod="upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": object_key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        ))

    def complete_multipart_upload(self, object_key: str, upload_id: str, parts: list[dict[str, Any]]) -> StoredObject:
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=object_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        return self.head(object_key)

    def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        self.client.abort_multipart_upload(Bucket=self.bucket, Key=object_key, UploadId=upload_id)

    def head(self, object_key: str) -> StoredObject:
        result = self.client.head_object(Bucket=self.bucket, Key=object_key)
        return StoredObject(
            object_key=object_key,
            size_bytes=int(result["ContentLength"]),
            etag=str(result.get("ETag") or ""),
        )

    def presign_download(self, object_key: str, file_name: str, content_type: str | None, expires_in: int) -> str:
        parameters: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": object_key,
            "ResponseContentDisposition": f'attachment; filename="{file_name.replace(chr(34), "")}"',
        }
        if content_type:
            parameters["ResponseContentType"] = content_type
        return str(self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params=parameters,
            ExpiresIn=expires_in,
            HttpMethod="GET",
        ))

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)


def storage_from_config(config: GatewayConfig) -> StorageAdapter:
    if config.storage_provider == "mock":
        return MockStorageAdapter.from_xdg()
    return SpacesStorageAdapter(
        endpoint=config.storage_endpoint,
        region=config.storage_region,
        bucket=config.storage_bucket,
        access_key_id=config.storage_access_key_id,
        secret_access_key=config.storage_secret_access_key,
    )


def multipart_part_size(size_bytes: int, configured_part_size: int) -> int:
    if size_bytes < 0:
        raise ValueError("upload_size_invalid")
    if size_bytes > MAX_OBJECT_BYTES:
        raise ValueError("upload_size_exceeds_provider_limit")
    part_size = max(configured_part_size, math.ceil(max(1, size_bytes) / 10_000))
    if part_size > MAX_MULTIPART_PART_BYTES:
        raise ValueError("upload_part_size_exceeds_provider_limit")
    return part_size
