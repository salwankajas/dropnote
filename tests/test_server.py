import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

import server
from server import CampaignCreate, VerifyRequest


class FileResourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.previous_db_path = server.DB_PATH
        self.previous_upload_dir = server.UPLOAD_DIR
        server.DB_PATH = self.root / "test.sqlite3"
        server.UPLOAD_DIR = self.root / "private-uploads"
        server.init_db()
        self.user = {"email": "creator@example.test", "role": "creator"}

    def tearDown(self):
        server.DB_PATH = self.previous_db_path
        server.UPLOAD_DIR = self.previous_upload_dir
        self.temp_dir.cleanup()

    async def make_request(self, content: bytes, filename: str) -> Request:
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": content, "more_body": False}
            return {"type": "http.disconnect"}

        encoded_name = quote(filename, safe="").encode("ascii")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/resources/upload",
            "raw_path": b"/api/resources/upload",
            "query_string": b"",
            "headers": [
                (b"x-file-name", encoded_name),
                (b"content-length", str(len(content)).encode()),
                (b"content-type", b"application/octet-stream"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
        return Request(scope, receive)

    async def test_upload_is_private_and_requires_verified_claim_to_download(self):
        pdf = b"%PDF-1.4\nDropnote test resource\n%%EOF"
        request = await self.make_request(pdf, "../../Creator Guide.pdf")
        uploaded = await server.upload_resource(request, self.user)

        create_payload = CampaignCreate(
            id="file-drop",
            title="File drop",
            channel="Test creator",
            resourceType="file",
            resource=uploaded["fileId"],
            video="https://youtu.be/mQJXPxb0sQc",
        )
        with patch.object(server, "extract_video_id", return_value="mQJXPxb0sQc"):
            server.create_campaign(create_payload, self.user)

        public_campaigns = server.list_campaigns()
        public_campaign = next(row for row in public_campaigns if row["campaign_id"] == "file-drop")
        self.assertNotIn("resource_file_id", public_campaign)
        self.assertEqual(uploaded["fileName"], "Creator Guide.pdf")

        class FakeDownloader:
            def get_comments(self, video_id, sort):
                return iter([{
                    "text": "The quiet fox wanders gently through forests.",
                    "channel": "youtube-channel-123",
                    "cid": "youtube-comment-456",
                }])

        payload = VerifyRequest(
            campaignId="file-drop",
            code="The quiet fox wanders gently through forests.",
        )
        with patch.object(server, "YoutubeCommentDownloader", FakeDownloader):
            result = server.verify_comment(payload)

        self.assertEqual(result["resourceType"], "file")
        self.assertEqual(result["resourceFileName"], "Creator Guide.pdf")
        self.assertTrue(result["downloadToken"])

        with self.assertRaises(HTTPException) as missing_token:
            server.download_campaign_resource("file-drop", "")
        self.assertEqual(missing_token.exception.status_code, 401)

        response = server.download_campaign_resource("file-drop", result["downloadToken"])
        self.assertEqual(response.filename, "Creator Guide.pdf")
        self.assertEqual(Path(response.path).read_bytes(), pdf)

    async def test_rejects_unsupported_and_invalid_files_without_leaving_uploads(self):
        request = await self.make_request(b"not an executable", "payload.exe")
        with self.assertRaises(HTTPException) as unsupported:
            await server.upload_resource(request, self.user)
        self.assertEqual(unsupported.exception.status_code, 415)
        self.assertEqual(list(server.UPLOAD_DIR.iterdir()), [])

        request = await self.make_request(b"not a pdf", "bad.pdf")
        with self.assertRaises(HTTPException) as invalid_pdf:
            await server.upload_resource(request, self.user)
        self.assertEqual(invalid_pdf.exception.status_code, 415)
        self.assertEqual(list(server.UPLOAD_DIR.iterdir()), [])

    def test_verification_request_cannot_include_email(self):
        with self.assertRaises(ValidationError):
            VerifyRequest(
                campaignId="campaign",
                code="The quiet fox wanders gently through forests.",
                email="private@example.test",
            )


if __name__ == "__main__":
    unittest.main()
