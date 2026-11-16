import unittest
from datetime import datetime

from clipper import virality


def msgs(spec):
    """spec: list of (offset_seconds, text) relative to t0 -> sorted message list"""
    t0 = 1_700_000_000.0
    return [(t0 + off, "user", text) for off, text in sorted(spec)]


def entry(start_off, duration, clip="clip.mp4"):
    return {
        "clip": clip,
        "start_iso": datetime.fromtimestamp(1_700_000_000.0 + start_off).isoformat(timespec="seconds"),
        "duration_seconds": duration,
    }


class TestGenreHits(unittest.TestCase):
    def test_hype_terms(self):
        self.assertIn("hype", virality.genre_hits("CLIP IT that was insane"))

    def test_worst_terms(self):
        self.assertIn("worst", virality.genre_hits("that was the WORST throw ever"))

    def test_surprise_terms(self):
        self.assertIn("surprise", virality.genre_hits("no way... HOW?!"))

    def test_word_boundary_w(self):
        # standalone W counts, the 'w' inside 'own' must not
        self.assertIn("hype", virality.genre_hits("W"))
        self.assertNotIn("hype", virality.genre_hits("he owns the lobby today"))

    def test_plain_chat_has_no_genre(self):
        self.assertEqual(virality.genre_hits("lol ya true"), {"funny"})
        self.assertEqual(virality.genre_hits("nice"), set())


class TestScoring(unittest.TestCase):
    def test_burst_beats_silence(self):
        quiet = msgs([(i * 10, "nice") for i in range(24)])
        burst = quiet + msgs([(120 + i * 0.1, "CLIP IT insane") for i in range(40)])
        quiet_scores = virality.score_clips(quiet, [entry(0, 40, "quiet.mp4")])
        burst_scores = virality.score_clips(burst, [entry(112, 48, "burst.mp4")])
        self.assertGreater(burst_scores[0]["virality"]["score"], quiet_scores[0]["virality"]["score"])

    def test_genres_tagged_from_chat(self):
        burst = msgs([(i * 10, "nice") for i in range(12)]) + [
            (1_700_000_000.0 + 120 + i * 0.1, "user", "no way HOW?!") for i in range(10)
        ]
        scored = virality.score_clips(burst, [entry(112, 48)])
        self.assertIn("surprise", scored[0]["virality"]["genres"])
        self.assertEqual(scored[0]["virality"]["rank"], 1)

    def test_ranking_order_and_recommended(self):
        burst = msgs([(i * 10, "nice") for i in range(12)]) + [
            (1_700_000_000.0 + 120 + i * 0.1, "user", "CLIP IT insane clutch") for i in range(30)
        ]
        entries = [entry(0, 30, "a.mp4"), entry(112, 48, "b.mp4")]
        scored = virality.score_clips(burst, entries)
        self.assertEqual(scored[0]["virality"]["rank"], 1)
        self.assertEqual(scored[0]["clip"], "b.mp4")
        recommended = [e for e in scored if e["virality"]["recommended"]]
        self.assertTrue(recommended)

    def test_zero_messages_does_not_crash(self):
        scored = virality.score_clips([], [entry(0, 45)])
        self.assertEqual(len(scored), 1)
        self.assertGreaterEqual(scored[0]["virality"]["score"], 0)


if __name__ == "__main__":
    unittest.main()
