"""Guards on the paths that drove token spend on large projects."""
import asyncio
import unittest
from typing import List, Optional

from src.core.translators.services import LocalLLMTranslator, OpenAICompatibleTranslator
from src.core.translation_quality import translation_issues


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class CountingTranslator(LocalLLMTranslator):
    """Records every batch handed to the transport, and can fail on demand."""

    def __init__(self, fail_sizes=(), **kwargs) -> None:
        kwargs.setdefault("model", "test")
        super().__init__(**kwargs)
        self.calls: List[List[str]] = []
        self.fail_sizes = set(fail_sizes)

    async def _translate_clean_texts(
        self, clean_texts: List[str], source_lang: str, target_lang: str
    ) -> List[Optional[str]]:
        self.calls.append(list(clean_texts))
        if len(clean_texts) in self.fail_sizes:
            return []  # malformed: wrong length
        return [f"EN:{t}" for t in clean_texts]


class SplitFallbackTests(unittest.TestCase):
    def test_happy_path_is_one_call(self) -> None:
        tr = CountingTranslator()
        out = _run(tr._translate_with_retry_and_fallback(["a", "b", "c"], "ja", "en"))
        self.assertEqual(out, ["EN:a", "EN:b", "EN:c"])
        self.assertEqual(len(tr.calls), 1)

    def test_failure_halves_instead_of_one_call_per_line(self) -> None:
        """The old code issued len(batch) calls; the cap is 1 + 2 + 4."""
        batch = [f"line{i}" for i in range(16)]
        tr = CountingTranslator(fail_sizes={16})
        _run(tr._translate_with_retry_and_fallback(batch, "ja", "en"))
        self.assertLessEqual(len(tr.calls), 7)
        self.assertLess(len(tr.calls), len(batch))

    def test_good_half_is_still_translated(self) -> None:
        batch = [f"line{i}" for i in range(8)]
        tr = CountingTranslator(fail_sizes={8})
        out = _run(tr._translate_with_retry_and_fallback(batch, "ja", "en"))
        self.assertEqual(len(out), 8)
        self.assertTrue(all(v == f"EN:line{i}" for i, v in enumerate(out)))

    def test_hopeless_batch_gives_up_bounded(self) -> None:
        """Every size fails: cost must stay bounded, unresolved items are None."""
        batch = [f"line{i}" for i in range(32)]
        tr = CountingTranslator(fail_sizes=set(range(1, 33)))
        out = _run(tr._translate_with_retry_and_fallback(batch, "ja", "en"))
        self.assertEqual(len(out), 32)
        self.assertTrue(all(v is None for v in out))
        self.assertLessEqual(len(tr.calls), 16)


class OutputBudgetTests(unittest.TestCase):
    def test_budget_scales_with_input(self) -> None:
        small = OpenAICompatibleTranslator._output_token_budget(["abc"])
        large = OpenAICompatibleTranslator._output_token_budget(["x" * 6000])
        self.assertLess(small, large)

    def test_budget_is_clamped(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._output_token_budget([""]),
            OpenAICompatibleTranslator.OUTPUT_BUDGET_MIN,
        )
        self.assertEqual(
            OpenAICompatibleTranslator._output_token_budget(["x" * 500000]),
            OpenAICompatibleTranslator.OUTPUT_BUDGET_MAX,
        )


class LineBreakToleranceTests(unittest.TestCase):
    def test_single_reflow_is_accepted(self) -> None:
        self.assertEqual(translation_issues("ああ\nいい", "Aa Ii"), [])

    def test_large_drift_still_flagged(self) -> None:
        self.assertIn("line break count changed", translation_issues("a\nb\nc\nd", "abcd"))

    def test_escape_codes_still_enforced(self) -> None:
        self.assertIn("game codes or tags changed", translation_issues("\\V[1] hi", "hello"))

    def test_empty_still_flagged(self) -> None:
        self.assertEqual(translation_issues("a", "  "), ["empty translation"])


if __name__ == "__main__":
    unittest.main()
