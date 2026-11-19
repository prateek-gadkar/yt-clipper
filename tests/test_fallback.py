import unittest

from clipper.watch import _should_fallback


class TestShouldFallback(unittest.TestCase):
    def test_unavailable_specific_quality_falls_back(self):
        self.assertTrue(_should_fallback("720p", recording_started=False, already_fell_back=False))

    def test_no_fallback_once_recording_started(self):
        self.assertFalse(_should_fallback("720p", recording_started=True, already_fell_back=False))

    def test_no_double_fallback(self):
        self.assertFalse(_should_fallback("720p", recording_started=False, already_fell_back=True))

    def test_best_never_falls_back(self):
        self.assertFalse(_should_fallback("best", recording_started=False, already_fell_back=False))

    def test_best_family_never_falls_back(self):
        for q in ("worst", "best-audio", "worst-audio", "BEST"):
            self.assertFalse(_should_fallback(q, recording_started=False, already_fell_back=False))


if __name__ == "__main__":
    unittest.main()
