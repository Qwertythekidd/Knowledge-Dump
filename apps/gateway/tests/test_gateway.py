from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import select

from apps.gateway.knowledge_dump_gateway.schema import accounts, sessions
from apps.gateway.knowledge_dump_gateway.server import create_server
from apps.gateway.knowledge_dump_gateway.store import Catalog, DEMO_EMAIL, DEMO_PASSWORD


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.catalog = Catalog(Path(self.temporary.name) / "catalog.db")
        self.server = create_server(host="127.0.0.1", port=0, catalog=self.catalog)
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

    def test_health_and_authentication_boundaries(self) -> None:
        status, health = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["schemaVersion"], 2)
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
        status, refreshed = self.request(
            "POST",
            "/api/v1/auth/refresh",
            {"refreshToken": original["refreshToken"]},
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(refreshed["accessToken"], original["accessToken"])
        self.assertNotEqual(refreshed["refreshToken"], original["refreshToken"])
        self.assertEqual(self.error("GET", "/api/v1/auth/session", token=original["accessToken"])[0], 401)
        self.assertEqual(self.error("POST", "/api/v1/auth/refresh", {"refreshToken": original["refreshToken"]})[0], 401)
        self.assertEqual(self.request("GET", "/api/v1/auth/session", token=refreshed["accessToken"])[0], 200)

    def test_file_lifecycle_creates_immutable_versions(self) -> None:
        token = self.login()["accessToken"]
        status, created = self.request("POST", "/api/v1/folders", {"name": "Migration", "parentId": None}, token)
        self.assertEqual(status, 201)
        folder_id = created["file"]["id"]

        status, uploaded = self.request(
            "POST",
            "/api/v1/files",
            {
                "name": "context.jsonl",
                "parentId": folder_id,
                "kind": "document",
                "mimeType": "application/jsonl",
                "sizeBytes": 1024,
            },
            token,
        )
        self.assertEqual(status, 201)
        file_id = uploaded["file"]["id"]
        self.request("PATCH", f"/api/v1/files/{file_id}", {"name": "context-v2.jsonl"}, token)
        status, archived = self.request("POST", f"/api/v1/files/{file_id}/archive", {}, token)
        self.assertEqual(status, 200)
        self.assertEqual(archived["file"]["status"], "archived")

        status, versions = self.request("GET", f"/api/v1/files/{file_id}/versions", token=token)
        self.assertEqual(status, 200)
        self.assertEqual([version["version"] for version in versions["versions"]], [3, 2, 1])
        self.assertEqual(versions["versions"][0]["metadata"]["status"], "archived")

    def test_accounts_cannot_read_each_others_catalogs(self) -> None:
        self.catalog.create_account(
            email="second@example.test",
            password="correct horse battery staple",
            display_name="Second Operator",
        )
        first = self.login()
        second = self.login("second@example.test", "correct horse battery staple")
        self.request("POST", "/api/v1/folders", {"name": "Second private folder"}, second["accessToken"])
        _, first_files = self.request("GET", "/api/v1/files", token=first["accessToken"])
        _, second_files = self.request("GET", "/api/v1/files", token=second["accessToken"])
        self.assertNotIn("Second private folder", [item["name"] for item in first_files["files"]])
        self.assertIn("Second private folder", [item["name"] for item in second_files["files"]])

    def test_device_revocation_invalidates_its_sessions(self) -> None:
        first = self.login()
        second = self.login()
        status, result = self.request(
            "DELETE",
            f"/api/v1/devices/{first['device']['id']}",
            token=second["accessToken"],
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["revoked"])
        self.assertEqual(self.error("GET", "/api/v1/auth/session", token=first["accessToken"])[0], 401)
        self.assertEqual(self.request("GET", "/api/v1/auth/session", token=second["accessToken"])[0], 200)

    def test_quota_is_enforced_before_metadata_commit(self) -> None:
        self.catalog.create_account(
            email="tiny@example.test",
            password="correct horse battery staple",
            display_name="Tiny Quota",
            quota_bytes=10,
            quota_objects=1,
        )
        token = self.login("tiny@example.test", "correct horse battery staple")["accessToken"]
        status, payload = self.error(
            "POST",
            "/api/v1/files",
            {"name": "too-large.bin", "kind": "other", "sizeBytes": 11},
            token,
        )
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "quota_bytes_exceeded")
        _, listing = self.request("GET", "/api/v1/files", token=token)
        self.assertEqual(listing["files"], [])

    def test_folder_cycles_are_rejected(self) -> None:
        token = self.login()["accessToken"]
        _, parent = self.request("POST", "/api/v1/folders", {"name": "Parent"}, token)
        _, child = self.request(
            "POST",
            "/api/v1/folders",
            {"name": "Child", "parentId": parent["file"]["id"]},
            token,
        )
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
