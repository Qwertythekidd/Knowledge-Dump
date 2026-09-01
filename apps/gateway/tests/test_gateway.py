from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select, update

from apps.gateway.knowledge_dump_gateway.schema import accounts, sessions, upload_sessions
from apps.gateway.knowledge_dump_gateway.server import cleanup_expired_uploads, create_server
from apps.gateway.knowledge_dump_gateway.storage import MockStorageAdapter
from apps.gateway.knowledge_dump_gateway.store import Catalog, DEMO_EMAIL, DEMO_PASSWORD


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.catalog = Catalog(Path(self.temporary.name) / "catalog.db")
        self.catalog.config = replace(self.catalog.config, multipart_part_bytes=5, transfer_url_seconds=60)
        self.storage = MockStorageAdapter(Path(self.temporary.name) / "objects")
        self.server = create_server(host="127.0.0.1", port=0, catalog=self.catalog, storage=self.storage)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method: str, path: str, payload=None, token: str | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())

    def raw_request(self, method: str, path: str, content: bytes | None = None, headers: dict[str, str] | None = None):
        request = urllib.request.Request(f"{self.base_url}{path}", data=content, headers=headers or {}, method=method)
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), dict(response.headers)

    def error(self, method: str, path: str, payload=None, token: str | None = None) -> tuple[int, dict]:
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request(method, path, payload, token)
        return failure.exception.code, json.loads(failure.exception.read())

    def login(self, email: str = DEMO_EMAIL, password: str = DEMO_PASSWORD, device_id: str | None = None) -> dict:
        status, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            {
                "email": email,
                "password": password,
                "deviceId": device_id,
                "deviceLabel": "Gateway test workstation",
                "platform": "test",
            },
        )
        self.assertEqual(status, 200)
        return payload

    def start_upload(self, token: str, name: str, content: bytes, parent_id: str | None = None) -> dict:
        status, payload = self.request(
            "POST",
            "/api/v1/uploads",
            {
                "name": name,
                "parentId": parent_id,
                "kind": "document",
                "mimeType": "application/octet-stream",
                "sizeBytes": len(content),
            },
            token,
        )
        self.assertEqual(status, 201)
        return payload["upload"]

    def upload_parts(self, token: str, upload: dict, content: bytes, only: list[int] | None = None) -> dict:
        part_numbers = only or list(range(1, upload["totalParts"] + 1))
        _, grants = self.request(
            "POST",
            f"/api/v1/uploads/{upload['id']}/parts",
            {"partNumbers": part_numbers},
            token,
        )
        current = upload
        for grant in grants["parts"]:
            part_number = grant["partNumber"]
            start = (part_number - 1) * upload["partSize"]
            chunk = content[start:start + upload["partSize"]]
            status, _, headers = self.raw_request("PUT", f"/api{grant['url']}", chunk)
            self.assertEqual(status, 200)
            _, reported = self.request(
                "POST",
                f"/api/v1/uploads/{upload['id']}/parts/{part_number}/complete",
                {"etag": headers["ETag"], "sizeBytes": len(chunk)},
                token,
            )
            current = reported["upload"]
        return current

    def complete_upload(self, token: str, upload_id: str) -> dict:
        status, result = self.request("POST", f"/api/v1/uploads/{upload_id}/complete", {}, token)
        self.assertEqual(status, 200)
        return result

    def upload(self, token: str, name: str, content: bytes, parent_id: str | None = None) -> dict:
        upload = self.start_upload(token, name, content, parent_id)
        self.upload_parts(token, upload, content)
        return self.complete_upload(token, upload["id"])

    def test_health_and_authentication_boundaries(self) -> None:
        status, health = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["schemaVersion"], 3)
        self.assertEqual(self.error("GET", "/api/v1/files")[0], 401)

        authenticated = self.login()
        status, storage = self.request("GET", "/api/v1/storage/health", token=authenticated["accessToken"])
        self.assertEqual(status, 200)
        self.assertTrue(storage["readAccess"])
        self.assertTrue(storage["writeAccess"])
        self.assertEqual(storage["database"], "sqlite")

    def test_passwords_and_tokens_are_not_stored_in_plaintext(self) -> None:
        authenticated = self.login()
        with self.catalog.engine.connect() as connection:
            account_row = connection.execute(select(accounts).where(accounts.c.email == DEMO_EMAIL)).mappings().one()
            session_row = connection.execute(select(sessions).where(sessions.c.account_id == account_row["id"])).mappings().one()
        self.assertTrue(account_row["password_hash"].startswith("$argon2id$"))
        self.assertNotIn(DEMO_PASSWORD, account_row["password_hash"])
        self.assertNotEqual(session_row["access_token_hash"], authenticated["accessToken"])
        self.assertNotEqual(session_row["refresh_token_hash"], authenticated["refreshToken"])

    def test_refresh_rotates_both_tokens_and_invalidates_old_access(self) -> None:
        original = self.login()
        _, refreshed = self.request("POST", "/api/v1/auth/refresh", {"refreshToken": original["refreshToken"]})
        self.assertNotEqual(refreshed["accessToken"], original["accessToken"])
        self.assertNotEqual(refreshed["refreshToken"], original["refreshToken"])
        self.assertEqual(self.error("GET", "/api/v1/auth/session", token=original["accessToken"])[0], 401)
        self.assertEqual(self.error("POST", "/api/v1/auth/refresh", {"refreshToken": original["refreshToken"]})[0], 401)

    def test_multipart_upload_is_hidden_until_verified_and_downloads_exact_bytes(self) -> None:
        token = self.login()["accessToken"]
        content = b"alpha-beta-gamma"
        upload = self.start_upload(token, "context.bin", content)
        _, before = self.request("GET", "/api/v1/files", token=token)
        self.assertNotIn("context.bin", [item["name"] for item in before["files"]])

        self.upload_parts(token, upload, content)
        completed = self.complete_upload(token, upload["id"])
        file_item = completed["file"]
        self.assertEqual(file_item["sizeBytes"], len(content))

        _, grant = self.request("POST", f"/api/v1/files/{file_item['id']}/download", {}, token)
        status, body, headers = self.raw_request("GET", f"/api{grant['url']}")
        self.assertEqual(status, 200)
        self.assertEqual(body, content)
        self.assertEqual(headers["Accept-Ranges"], "bytes")

        status, body, headers = self.raw_request("GET", f"/api{grant['url']}", headers={"Range": "bytes=6-9"})
        self.assertEqual(status, 206)
        self.assertEqual(body, b"beta")
        self.assertEqual(headers["Content-Range"], f"bytes 6-9/{len(content)}")

    def test_interrupted_upload_resumes_from_durable_part_checkpoint(self) -> None:
        token = self.login()["accessToken"]
        content = b"0123456789abcdef"
        upload = self.start_upload(token, "resume.bin", content)
        partial = self.upload_parts(token, upload, content, [1, 2])
        self.assertEqual([part["partNumber"] for part in partial["completedParts"]], [1, 2])

        _, restored = self.request("GET", f"/api/v1/uploads/{upload['id']}", token=token)
        self.assertEqual([part["partNumber"] for part in restored["upload"]["completedParts"]], [1, 2])
        self.upload_parts(token, restored["upload"], content, [3, 4])
        with self.catalog.engine.begin() as connection:
            connection.execute(update(upload_sessions).where(upload_sessions.c.id == upload["id"]).values(status="completing"))
        result = self.complete_upload(token, upload["id"])
        self.assertEqual(result["upload"]["status"], "completed")
        repeated = self.complete_upload(token, upload["id"])
        self.assertEqual(repeated["file"]["id"], result["file"]["id"])

    def test_incomplete_upload_cannot_commit_and_abort_releases_it(self) -> None:
        token = self.login()["accessToken"]
        content = b"incomplete"
        upload = self.start_upload(token, "partial.bin", content)
        self.upload_parts(token, upload, content, [1])
        status, payload = self.error("POST", f"/api/v1/uploads/{upload['id']}/complete", {}, token)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "upload_parts_incomplete")
        status, aborted = self.request("DELETE", f"/api/v1/uploads/{upload['id']}", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(aborted["aborted"])
        _, restored = self.request("GET", f"/api/v1/uploads/{upload['id']}", token=token)
        self.assertEqual(restored["upload"]["status"], "aborted")

    def test_expired_upload_cleanup_aborts_provider_state(self) -> None:
        token = self.login()["accessToken"]
        upload = self.start_upload(token, "expired.bin", b"expired")
        with self.catalog.engine.begin() as connection:
            connection.execute(update(upload_sessions).where(upload_sessions.c.id == upload["id"]).values(
                expires_at="2000-01-01T00:00:00+00:00",
            ))
        self.assertEqual(cleanup_expired_uploads(self.catalog, self.storage), 1)
        _, restored = self.request("GET", f"/api/v1/uploads/{upload['id']}", token=token)
        self.assertEqual(restored["upload"]["status"], "expired")

    def test_file_lifecycle_preserves_object_bytes_and_versions(self) -> None:
        token = self.login()["accessToken"]
        _, created = self.request("POST", "/api/v1/folders", {"name": "Migration", "parentId": None}, token)
        folder_id = created["file"]["id"]
        uploaded = self.upload(token, "context.jsonl", b"{}\n", folder_id)
        file_id = uploaded["file"]["id"]
        self.request("PATCH", f"/api/v1/files/{file_id}", {"name": "context-v2.jsonl"}, token)
        _, archived = self.request("POST", f"/api/v1/files/{file_id}/archive", {}, token)
        self.assertEqual(archived["file"]["status"], "archived")
        _, versions = self.request("GET", f"/api/v1/files/{file_id}/versions", token=token)
        self.assertEqual([version["version"] for version in versions["versions"]], [3, 2, 1])
        self.assertEqual(versions["versions"][0]["metadata"]["status"], "archived")

    def test_accounts_cannot_read_catalogs_uploads_or_downloads_across_boundaries(self) -> None:
        self.catalog.create_account(
            email="second@example.test",
            password="correct horse battery staple",
            display_name="Second Operator",
        )
        first = self.login()
        second = self.login("second@example.test", "correct horse battery staple")
        uploaded = self.upload(second["accessToken"], "second-private.bin", b"private")
        file_id = uploaded["file"]["id"]
        upload_id = uploaded["upload"]["id"]
        self.assertEqual(self.error("GET", f"/api/v1/uploads/{upload_id}", token=first["accessToken"])[0], 404)
        self.assertEqual(self.error("POST", f"/api/v1/files/{file_id}/download", {}, first["accessToken"])[0], 404)

    def test_device_revocation_invalidates_its_sessions(self) -> None:
        first = self.login()
        second = self.login()
        status, result = self.request("DELETE", f"/api/v1/devices/{first['device']['id']}", token=second["accessToken"])
        self.assertEqual(status, 200)
        self.assertTrue(result["revoked"])
        self.assertEqual(self.error("GET", "/api/v1/auth/session", token=first["accessToken"])[0], 401)

    def test_quota_reserves_active_uploads_before_object_commit(self) -> None:
        self.catalog.create_account(
            email="tiny@example.test",
            password="correct horse battery staple",
            display_name="Tiny Quota",
            quota_bytes=10,
            quota_objects=1,
        )
        token = self.login("tiny@example.test", "correct horse battery staple")["accessToken"]
        first = self.start_upload(token, "reserved.bin", b"123456")
        status, payload = self.error(
            "POST",
            "/api/v1/uploads",
            {"name": "overflow.bin", "kind": "other", "sizeBytes": 5},
            token,
        )
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "quota_bytes_exceeded")
        self.request("DELETE", f"/api/v1/uploads/{first['id']}", token=token)
        self.assertEqual(self.request(
            "POST",
            "/api/v1/uploads",
            {"name": "after-abort.bin", "kind": "other", "sizeBytes": 5},
            token,
        )[0], 201)

    def test_folder_cycles_are_rejected(self) -> None:
        token = self.login()["accessToken"]
        _, parent = self.request("POST", "/api/v1/folders", {"name": "Parent"}, token)
        _, child = self.request("POST", "/api/v1/folders", {"name": "Child", "parentId": parent["file"]["id"]}, token)
        status, payload = self.error(
            "PATCH",
            f"/api/v1/files/{parent['file']['id']}",
            {"parentId": child["file"]["id"]},
            token,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "folder_cycle_not_allowed")


if __name__ == "__main__":
    unittest.main()
