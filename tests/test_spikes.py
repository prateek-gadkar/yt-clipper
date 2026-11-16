import unittest

from clipper.spikes import clip_windows, find_spikes, read_chat_log


def synth_times(buckets, seed=1):
    """buckets: list of message counts per 10s bucket."""
    import random

    random.seed(seed)
    times = []
    for i, n in enumerate(buckets):
        for _ in range(n):
            times.append(i * 10 + random.uniform(0, 9.9))
    return times


class TestFindSpikes(unittest.TestCase):
    def test_burst_is_detected(self):
        # 5 minutes of quiet (2-3 msg/bucket) then a 25-msg burst
        buckets = [2, 3, 2, 3, 2, 3, 2, 2, 3, 2, 3, 2, 28, 30, 25, 3, 2, 2] + [2] * 12
        spikes = find_spikes(synth_times(buckets), min_messages=6)
        self.assertEqual(len(spikes), 1)
        self.assertAlmostEqual(spikes[0].start, 120, delta=1)
        self.assertAlmostEqual(spikes[0].end, 150, delta=1)
        self.assertGreaterEqual(spikes[0].peak_count, 25)

    def test_quiet_channel_stays_quiet(self):
        spikes = find_spikes(synth_times([1, 2, 1, 0, 2, 1] * 10), min_messages=6)
        self.assertEqual(spikes, [])

    def test_steady_chatter_is_not_a_spike(self):
        # a uniformly busy channel: nothing is 3x the trailing average
        spikes = find_spikes(synth_times([20] * 40), min_messages=6)
        self.assertEqual(spikes, [])

    def test_adjacent_burst_buckets_merge_into_one_moment(self):
        buckets = [2] * 10 + [30, 4, 28, 9] + [2] * 10
        spikes = find_spikes(synth_times(buckets), min_messages=6, merge_gap_seconds=30)
        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0].buckets, 4)

    def test_empty_log(self):
        self.assertEqual(find_spikes([]), [])

    def test_clip_windows_precede_spike_and_cap(self):
        buckets = [2] * 10 + [30, 28, 25] + [2] * 10
        spikes = find_spikes(synth_times(buckets), min_messages=6)
        windows = clip_windows(spikes, pre_pad=8, post_pad=10, max_clip=60, min_clip=5)
        self.assertEqual(len(windows), 1)
        start, end = windows[0]
        self.assertAlmostEqual(start, spikes[0].start - 8, delta=0.01)
        self.assertLessEqual(end - start, 60)


class TestReadChatLog(unittest.TestCase):
    def test_roundtrip(self):
        import tempfile
        from pathlib import Path

        from clipper.irc import format_log_line

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "chat.log"
            log.write_text(
                format_log_line(1_700_000_000_000, "user_a", "hello world")
                + format_log_line(1_700_000_005_000, "user_b", "with\ttab and newline\n")
            )
            msgs = read_chat_log(str(log))
            self.assertEqual(len(msgs), 2)
            self.assertAlmostEqual(msgs[0][0], 1_700_000_000.0)
            self.assertIn("hello world", msgs[0][2])
            self.assertNotIn("\t", msgs[1][2])


if __name__ == "__main__":
    unittest.main()
