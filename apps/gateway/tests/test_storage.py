from __future__ import annotations

import unittest

from apps.gateway.knowledge_dump_gateway.storage import SpacesStorageAdapter


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def head_bucket(self, **kwargs):
        self.calls.append(("head_bucket", kwargs))

    def create_multipart_upload(self, **kwargs):
        self.calls.append(("create_multipart_upload", kwargs))
        return {"UploadId": "provider-upload"}

    def generate_presigned_url(self, **kwargs):
        self.calls.append(("generate_presigned_url", kwargs))
        return f"https://signed.example/{kwargs['ClientMethod']}"

    def complete_multipart_upload(self, **kwargs):
        self.calls.append(("complete_multipart_upload", kwargs))

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        return {"ContentLength": 12, "ETag": '"provider-etag"'}

    def abort_multipart_upload(self, **kwargs):
        self.calls.append(("abort_multipart_upload", kwargs))

    def delete_object(self, **kwargs):
        self.calls.append(("delete_object", kwargs))


class SpacesStorageAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeS3Client()
        self.adapter = SpacesStorageAdapter(
            endpoint="https://nyc3.digitaloceanspaces.com",
            region="nyc3",
            bucket="private-space",
            client=self.client,
        )

    def test_multipart_and_presigned_operations_use_private_bucket_contract(self) -> None:
        self.assertTrue(self.adapter.health())
        self.assertEqual(self.adapter.create_multipart_upload("objects/a/opaque", "text/plain"), "provider-upload")
        part_url = self.adapter.presign_upload_part("objects/a/opaque", "provider-upload", 2, 900)
        self.assertEqual(part_url, "https://signed.example/upload_part")
        completed = self.adapter.complete_multipart_upload(
            "objects/a/opaque",
            "provider-upload",
            [{"PartNumber": 1, "ETag": '"one"'}],
        )
        self.assertEqual(completed.size_bytes, 12)
        self.assertEqual(completed.etag, '"provider-etag"')
        download_url = self.adapter.presign_download("objects/a/opaque", "notes.txt", "text/plain", 900)
        self.assertEqual(download_url, "https://signed.example/get_object")
        self.adapter.abort_multipart_upload("objects/a/opaque", "provider-upload")
        self.adapter.delete("objects/a/opaque")

        create = next(value for name, value in self.client.calls if name == "create_multipart_upload")
        self.assertEqual(create["ACL"], "private")
        signed_part = next(value for name, value in self.client.calls if name == "generate_presigned_url" and value["ClientMethod"] == "upload_part")
        self.assertEqual(signed_part["HttpMethod"], "PUT")
        self.assertEqual(signed_part["Params"]["PartNumber"], 2)
        complete = next(value for name, value in self.client.calls if name == "complete_multipart_upload")
        self.assertEqual(complete["MultipartUpload"]["Parts"][0]["ETag"], '"one"')


if __name__ == "__main__":
    unittest.main()
