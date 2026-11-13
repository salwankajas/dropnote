import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import server
from server import VerifyRequest


class FakeDownloader:
    """Stands in for the network scraper and counts how often it is used."""

    calls = 0

    def get_comments(self, video_id, sort_by_recent):
        FakeDownloader.calls += 1
        for index in range(3):
            yield {
                "text": f"drop the code {index}",
                "channel": f"channel-{index}",
                "cid": f"comment-{index}",
            }


class CommentCacheTests(unittest.TestCase):
    def setUp(self):
        server._comment_cache.clear()
        server._comment_locks.clear()
        FakeDownloader.calls = 0
        self.scraper = patch.object(server, "YoutubeCommentDownloader", FakeDownloader)
        self.scraper.start()

    def tearDown(self):
        self.scraper.stop()
        server._comment_cache.clear()
        server._comment_locks.clear()

    def test_repeated_checks_share_one_scrape(self):
        first = server.recent_comments("dQw4w9WgXcQ")
        second = server.recent_comments("dQw4w9WgXcQ")

        self.assertEqual(FakeDownloader.calls, 1)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["channel"], "channel-0")
        self.assertEqual(first[0]["cid"], "comment-0")

    def test_parallel_checks_share_one_scrape(self):
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(server.recent_comments("dQw4w9WgXcQ"))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(FakeDownloader.calls, 1)
        self.assertEqual(len(results), 8)

    def test_expired_entry_is_refreshed(self):
        server.recent_comments("dQw4w9WgXcQ")
        with patch.object(server, "COMMENT_CACHE_TTL", -1):
            server.recent_comments("dQw4w9WgXcQ")

        self.assertEqual(FakeDownloader.calls, 2)

    def test_cache_is_bounded(self):
        with patch.object(server, "COMMENT_CACHE_MAX_VIDEOS", 2):
            for index in range(5):
                server.recent_comments(f"video-{index}")

        self.assertLessEqual(len(server._comment_cache), 2)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.previous_db_path = server.DB_PATH
        self.previous_upload_dir = server.UPLOAD_DIR
        server.DB_PATH = self.root / "perf.sqlite3"
        server.UPLOAD_DIR = self.root / "uploads"
        server.init_db()

    def tearDown(self):
        server.DB_PATH = self.previous_db_path
        server.UPLOAD_DIR = self.previous_upload_dir
        self.temp_dir.cleanup()

    def test_wal_mode_and_claim_indexes(self):
        with closing(server.db()) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}

        self.assertIn("idx_claims_download_token", indexes)
        self.assertIn("idx_claims_campaign", indexes)
        self.assertIn("idx_campaigns_creator", indexes)

    def test_verification_records_one_claim_per_channel(self):
        with closing(server.db()) as conn:
            conn.execute(
                "INSERT INTO campaigns(campaign_id, title, channel, resource_url, video_url, initials) "
                "VALUES ('campaign-1', 'Test drop', 'Creator', 'https://example.test/file', "
                "'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'CR')",
            )
            conn.commit()

        server._comment_cache.clear()
        FakeDownloader.calls = 0
        with patch.object(server, "YoutubeCommentDownloader", FakeDownloader):
            first = server.verify_comment(VerifyRequest(campaignId="campaign-1", code="drop the code"))
            second = server.verify_comment(VerifyRequest(campaignId="campaign-1", code="drop the code"))

        self.assertTrue(first["verified"])
        self.assertFalse(first["alreadyClaimed"])
        self.assertTrue(second["alreadyClaimed"])
        self.assertEqual(FakeDownloader.calls, 1)
        with closing(server.db()) as conn:
            claimed = conn.execute("SELECT claimed FROM campaigns WHERE campaign_id = 'campaign-1'").fetchone()[0]
            claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        self.assertEqual(claimed, 1)
        self.assertEqual(claims, 1)


if __name__ == "__main__":
    unittest.main()
