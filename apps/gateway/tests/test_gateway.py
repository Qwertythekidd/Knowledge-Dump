from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from apps.gateway.knowledge_dump_gateway.server import create_server
from apps.gateway.knowledge_dump_gateway.store import Catalog


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        catalog = Catalog(Path(self.temporary.name) / "catalog.db")
        self.server = create_server(host="127.0.0.1", port=0, catalog=catalog)
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

    def login(self) -> str:
        status, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            {"email": "demo@knowledge-dump.local", "password": "knowledge"},
        )
        self.assertEqual(status, 200)
        return payload["accessToken"]

    def test_health_and_authentication_boundaries(self) -> None:
        status, health = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "healthy")
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request("GET", "/api/v1/files")
        self.assertEqual(failure.exception.code, 401)

        token = self.login()
        status, storage = self.request("GET", "/api/v1/storage/health", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(storage["readAccess"])
        self.assertTrue(storage["writeAccess"])

    def test_file_lifecycle_is_persisted(self) -> None:
        token = self.login()
        status, created = self.request(
            "POST",
            "/api/v1/folders",
            {"name": "Migration", "parentId": None},
            token,
        )
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

        status, listing = self.request("GET", f"/api/v1/files?parentId={folder_id}", token=token)
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in listing["files"]], ["context.jsonl"])

        status, archived = self.request("POST", f"/api/v1/files/{file_id}/archive", {}, token)
        self.assertEqual(status, 200)
        self.assertEqual(archived["file"]["status"], "archived")


if __name__ == "__main__":
    unittest.main()
