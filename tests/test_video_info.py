import unittest
from unittest.mock import Mock, patch

import server


class VideoInfoTests(unittest.TestCase):
    def setUp(self):
        server._video_info_cache.clear()

    def tearDown(self):
        server._video_info_cache.clear()

    def fetch(self, video="https://youtu.be/dQw4w9WgXcQ"):
        return server.youtube_video_info(
            server.VideoInfoRequest(video=video),
            user={"email": "creator@example.test"},
        )

    def test_metadata_is_normalized_and_cached(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "title": "A public video",
            "author_name": "Creator",
            "author_url": "https://www.youtube.com/@creator",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        }

        with patch.object(server.requests, "get", return_value=response) as get:
            first = self.fetch()
            second = self.fetch()

        self.assertEqual(get.call_count, 1)
        self.assertEqual(first["videoId"], "dQw4w9WgXcQ")
        self.assertEqual(first["title"], "A public video")
        self.assertEqual(first["channel"], "Creator")
        self.assertEqual(first["handle"], "@creator")
        self.assertEqual(second, first)

    def test_missing_video_returns_a_422(self):
        response = Mock(status_code=404)

        with patch.object(server.requests, "get", return_value=response):
            with self.assertRaises(server.HTTPException) as caught:
                self.fetch()

        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("could not find public video details", caught.exception.detail.lower())

    def test_network_failure_returns_a_502(self):
        with patch.object(
            server.requests,
            "get",
            side_effect=server.requests.RequestException("offline"),
        ):
            with self.assertRaises(server.HTTPException) as caught:
                self.fetch()

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("could not fetch youtube details", caught.exception.detail.lower())


if __name__ == "__main__":
    unittest.main()