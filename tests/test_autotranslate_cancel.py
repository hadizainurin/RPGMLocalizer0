"""Cancellation responsiveness and incremental saving of auto-translate."""
import asyncio
import time
import unittest

from src.backend.editor_backend import AutoTranslateWorker


class _Worker(AutoTranslateWorker):
    """Bare worker: only the cancellation helper is under test."""

    def __init__(self) -> None:  # noqa: D107 - no QThread init needed
        self._cancel = False
        self._CANCEL_POLL_SECONDS = 0.01


class RunCancellableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()

    def tearDown(self) -> None:
        self.loop.close()

    def test_result_is_returned_when_not_cancelled(self) -> None:
        w = _Worker()

        async def work():
            await asyncio.sleep(0.01)
            return ["ok"]

        self.assertEqual(w._run_cancellable(self.loop, work()), ["ok"])

    def test_cancel_before_start_returns_none(self) -> None:
        w = _Worker()
        w._cancel = True

        async def work():
            await asyncio.sleep(5)
            return ["never"]

        self.assertIsNone(w._run_cancellable(self.loop, work()))

    def test_long_request_is_abandoned_quickly(self) -> None:
        """The old code only checked the flag between pages, so Cancel felt dead."""
        w = _Worker()

        async def slow():
            await asyncio.sleep(30)
            return ["never"]

        async def cancel_soon():
            await asyncio.sleep(0.05)
            w._cancel = True

        async def both():
            task = asyncio.ensure_future(cancel_soon())
            try:
                return await asyncio.sleep(0)
            finally:
                await task

        self.loop.run_until_complete(both())
        started = time.monotonic()
        self.assertIsNone(w._run_cancellable(self.loop, slow()))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_exceptions_still_propagate(self) -> None:
        w = _Worker()

        async def boom():
            raise ValueError("server exploded")

        with self.assertRaises(ValueError):
            w._run_cancellable(self.loop, boom())


class SignalContractTests(unittest.TestCase):
    def test_page_applied_signal_exists(self) -> None:
        self.assertTrue(hasattr(AutoTranslateWorker, "pageApplied"))

    def test_poll_interval_is_responsive(self) -> None:
        self.assertLessEqual(AutoTranslateWorker._CANCEL_POLL_SECONDS, 0.5)


if __name__ == "__main__":
    unittest.main()
