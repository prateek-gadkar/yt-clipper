import unittest
from types import SimpleNamespace

from clipper.ytchat import chat_item_to_line, extract_video_id


class TestExtractVideoId(unittest.TestCase):
    def test_watch_url(self):
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_watch_url_with_extra_params(self):
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"), "dQw4w9WgXcQ")

    def test_live_url(self):
        self.assertEqual(extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_short_url(self):
        self.assertEqual(extract_video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_raw_id_passthrough(self):
        self.assertEqual(extract_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            extract_video_id("https://www.google.com/")


class TestChatItemToLine(unittest.TestCase):
    def test_text_item(self):
        item = SimpleNamespace(
            timestamp=1_700_000_000_123,
            author=SimpleNamespace(name="some viewer"),
            message="clip IT",
        )
        line = chat_item_to_line(item)
        self.assertIsNotNone(line)
        ts, iso, user, message = line.rstrip("\n").split("\t", 3)
        self.assertEqual(ts, "1700000000123")
        self.assertEqual(user, "some viewer")
        self.assertEqual(message, "clip IT")

    def test_empty_message_skipped(self):
        item = SimpleNamespace(
            timestamp=1_700_000_000_123,
            author=SimpleNamespace(name="viewer"),
            message="   ",
        )
        self.assertIsNone(chat_item_to_line(item))

    def test_missing_author_defaults(self):
        item = SimpleNamespace(timestamp=1_700_000_000_123, author=None, message="hi")
        self.assertIn("\tviewer\t", chat_item_to_line(item))


if __name__ == "__main__":
    unittest.main()
