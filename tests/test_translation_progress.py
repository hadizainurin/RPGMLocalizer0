"""Progress line estimated like a download: rough at once, refined over time."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from src.backend.editor_backend import TranslationProgress


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TranslationProgressTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.p = TranslationProgress(1000, clock=self.clock)

    def test_one_format_from_the_first_second(self):
        self.assertEqual(self.p.message(),
                         "0/1000 - 30 lines/min - Elapsed: 0s - Time remaining: 30m 00s")

    def test_elapsed_counts_the_whole_run(self):
        self.clock.t = 3725.0
        self.assertIn("Elapsed: 1h 02m 05s", self.p.message())

    def test_a_slow_request_raises_the_estimate_while_still_running(self):
        self.p.start_request(12)
        before = self.p.seconds_left()
        self.clock.t = 300.0           # five minutes, no reply yet
        after = self.p.seconds_left()
        self.assertGreater(after, before)

    def test_measurement_takes_over(self):
        # 120 lines measured at 1 line/s: the prior (0.5/s) fades out.
        for _ in range(10):
            self.p.start_request(12)
            self.clock.t += 12.0
            self.p.end_request(12)
            self.p.done += 12
        self.assertTrue(self.p.measured())
        self.assertAlmostEqual(self.p.rate(), (120 + 12) / (120 + 24), places=3)
        self.assertIn("55 lines/min", self.p.message())

    def test_cache_hits_count_as_done_not_as_engine_speed(self):
        self.p.done = 500                # answered from the cache
        rate_before = self.p.rate()
        self.assertAlmostEqual(rate_before, TranslationProgress.PRIOR_LINES_PER_SEC)
        # Few rows needed the engine so far -> share drops, time left drops.
        self.assertLess(self.p.engine_share(), 0.1)

    def test_rejected_replies_cost_time_without_lines(self):
        self.p.start_request(12)
        self.clock.t = 60.0
        self.p.end_request(0)
        self.assertLess(self.p.rate(), TranslationProgress.PRIOR_LINES_PER_SEC)

    def test_percent(self):
        self.p.done = 250
        self.assertEqual(self.p.percent(), 25)
        self.assertEqual(TranslationProgress(0).percent(), 100)


if __name__ == "__main__":
    unittest.main()
