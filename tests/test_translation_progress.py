"""The progress line: rate from engine work only, one format, live while waiting.

Before: rows answered from the cache counted toward the rate, so a page of
cache hits read "10384 strings/s"; the line froze while a local model worked
on a long request; then the rate collapsed and the time left disappeared.
"""
import os
import sys
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

    def test_cache_hits_do_not_inflate_the_rate(self):
        self.p.done = 100            # a page answered instantly from the cache
        self.assertIsNone(self.p.rate())
        self.assertIn("estimating", self.p.message())
        self.assertNotIn("lines/s", self.p.message())

    def test_rate_and_time_left_come_from_engine_work(self):
        self.p.done = 100
        self.p.start_request(100)
        self.clock.t = 200.0         # 100 lines took 200 s
        self.p.end_request(100)
        self.p.done = 200
        self.assertAlmostEqual(self.p.rate(), 0.5)
        # 800 rows left, half of rows so far needed the engine -> 400 / 0.5 = 800 s
        self.assertAlmostEqual(self.p.seconds_left(), 800.0)
        self.assertIn("30 lines/min", self.p.message())
        self.assertIn("13m 20s left", self.p.message())

    def test_message_stays_alive_during_a_long_request(self):
        self.p.start_request(15)
        self.clock.t = 75.0
        self.assertIn("translating 15 lines… 1m 15s", self.p.message())

    def test_retries_cost_time_without_adding_lines(self):
        self.p.start_request(10)
        self.clock.t = 10.0
        self.p.end_request(10)
        self.p.start_request(5)
        self.clock.t = 20.0
        self.p.end_request(0)
        self.assertAlmostEqual(self.p.rate(), 0.5)

    def test_percent(self):
        self.p.done = 250
        self.assertEqual(self.p.percent(), 25)
        self.assertEqual(TranslationProgress(0).percent(), 100)


if __name__ == "__main__":
    unittest.main()
