import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

import server
from server import CampaignCreate, VerifyRequest

VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class FakeDownloader:
    def get_comments(self, video_id, sort_by_recent):
        for index in range(2):
            yield {"text": f"drop the code {index}", "channel": f"channel-{index}", "cid": f"comment-{index}"}


class ResourceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.previous_db_path = server.DB_PATH
        server.DB_PATH = self.root / "test.sqlite3"
        server.init_db()
        server._comment_cache.clear()
        server._comment_locks.clear()
        self.scraper = patch.object(server, "YoutubeCommentDownloader", FakeDownloader)
        self.scraper.start()

    def tearDown(self):
        self.scraper.stop()
        server.DB_PATH = self.previous_db_path
        server._comment_cache.clear()
        server._comment_locks.clear()
        self.temp_dir.cleanup()

    def create_campaign(self, resource_type="link", resource="https://example.test/guide"):
        with closing(server.db()) as conn:
            conn.execute(
                "INSERT INTO campaigns(campaign_id,title,channel,resource_url,resource_type,resource_text,video_url,initials) "
                "VALUES('campaign-1','Test drop','Creator',?,?,?,?,'CR')",
                (resource if resource_type == "link" else "", resource_type, resource if resource_type == "text" else "", VIDEO_URL),
            )
            conn.commit()

    def verify(self):
        return server.verify_comment(VerifyRequest(campaignId="campaign-1", code="drop the code"))

    def test_link_is_revealed_after_verification(self):
        self.create_campaign("link", "https://example.test/guide")

        result = self.verify()

        self.assertTrue(result["verified"])
        self.assertEqual(result["resourceType"], "link")
        self.assertEqual(result["resourceUrl"], "https://example.test/guide")
        self.assertIsNone(result["resourceText"])
        self.assertNotIn("downloadToken", result)
        self.assertNotIn("resourceFileName", result)

    def test_text_is_revealed_after_verification(self):
        self.create_campaign("text", "the secret is 42")

        result = self.verify()

        self.assertEqual(result["resourceType"], "text")
        self.assertEqual(result["resourceText"], "the secret is 42")
        self.assertIsNone(result["resourceUrl"])

    def test_nothing_is_written_to_disk_beyond_the_database(self):
        self.create_campaign("text", "the secret is 42")

        self.verify()

        extra_files = [path.name for path in self.root.iterdir() if not path.name.startswith("test.sqlite3")]
        self.assertEqual(extra_files, [])

    def test_file_resource_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            CampaignCreate(
                id="campaign-1",
                title="Test drop",
                channel="Creator",
                resource="https://example.test/file.pdf",
                video=VIDEO_URL,
                resourceType="file",
            )

    def test_public_campaign_list_hides_the_resource(self):
        self.create_campaign("text", "the secret is 42")

        rows = server.list_campaigns()

        self.assertEqual(len(rows), 1)
        self.assertNotIn("resource_text", rows[0])
        self.assertNotIn("resource_url", rows[0])

    def test_no_file_storage_endpoints_remain(self):
        paths = {route.path for route in server.app.routes}

        self.assertNotIn("/api/resources/upload", paths)
        self.assertNotIn("/api/resources/upload/{file_id}", paths)
        self.assertNotIn("/api/campaigns/{campaign_id}/resource-file", paths)

    def test_claim_sentence_with_single_letter_word(self):
        self.create_campaign("link", "https://example.test/guide")
        with patch("server.recent_comments", return_value=[{"text": "A radiant musician thinks kindly across pastures.", "channel": "ch1", "cid": "c1"}]):
            result = server.verify_comment(VerifyRequest(campaignId="campaign-1", code="A radiant musician thinks kindly across pastures."))
            self.assertTrue(result["verified"])

    def test_batch_pause_and_resume_campaigns(self):
        self.create_campaign("link", "https://example.test/guide")
        admin_user = {"email": "admin@dropnote.local", "role": "admin"}
        server.batch_update_campaign_status(server.BatchStatusPayload(campaign_ids=["campaign-1"], status="Paused"), admin_user)
        rows = server.list_campaigns()
        self.assertEqual(rows[0]["status"], "Paused")

        server.batch_update_campaign_status(server.BatchStatusPayload(campaign_ids=[], status="Live"), admin_user)
        rows = server.list_campaigns()
        self.assertEqual(rows[0]["status"], "Live")

    def test_batch_delete_campaigns(self):
        self.create_campaign("link", "https://example.test/guide")
        admin_user = {"email": "admin@dropnote.local", "role": "admin"}
        server.batch_delete_campaigns(server.BatchDeletePayload(campaign_ids=["campaign-1"]), admin_user)
        rows = server.list_campaigns()
        self.assertEqual(len(rows), 0)

    def test_verification_request_cannot_include_email(self):
        with self.assertRaises(ValidationError):
            VerifyRequest(
                campaignId="campaign-1",
                code="drop the code 0",
                email="private@example.test",
            )


if __name__ == "__main__":
    unittest.main()
