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
            # A malformed answer: the server replied, but with the wrong number
            # of items. An empty list means "no response at all", which is a
            # transport failure and must NOT trigger the split path.
            return [f"EN:{t}" for t in clean_texts[:-1]]
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
    """max_tokens is opt-in. A client-side guess truncated normal responses,
    which broke JSON parsing and sent the batch down the split-retry path."""

    @staticmethod
    def _tr(**kwargs) -> LocalLLMTranslator:
        kwargs.setdefault("model", "test")
        return LocalLLMTranslator(**kwargs)

    def test_no_cap_by_default(self) -> None:
        tr = self._tr()
        self.assertEqual(tr._output_token_budget(["x" * 6000]), 0)
        self.assertEqual(tr._output_token_budget([""]), 0)

    def test_default_payload_omits_max_tokens(self) -> None:
        import inspect
        src = inspect.getsource(OpenAICompatibleTranslator._translate_clean_texts)
        self.assertIn("if budget > 0:", src)
        self.assertNotIn('"max_tokens": self._output_token_budget', src)

    def test_explicit_override_is_used_verbatim(self) -> None:
        tr = self._tr(max_tokens=12000)
        self.assertEqual(tr._output_token_budget(["abc"]), 12000)
        self.assertEqual(tr._output_token_budget(["x" * 500000]), 12000)

    def test_override_flows_from_settings(self) -> None:
        from src.core.translators.manager import create_translator
        tr = create_translator({"engine": "local_llm", "local_llm_max_tokens": 1024})
        self.assertEqual(tr._output_token_budget(["abc"]), 1024)

    def test_zero_setting_means_no_cap(self) -> None:
        from src.core.translators.manager import create_translator
        tr = create_translator({"engine": "local_llm", "local_llm_max_tokens": 0})
        self.assertEqual(tr._output_token_budget(["x" * 6000]), 0)

    def test_base_class_also_sends_no_cap(self) -> None:
        tr = OpenAICompatibleTranslator(api_key="", model="m", base_url="http://x/v1")
        self.assertEqual(tr._output_token_budget([""]), 0)


class LineBreakToleranceTests(unittest.TestCase):
    def test_single_reflow_is_accepted(self) -> None:
        self.assertEqual(translation_issues("ああ\nいい", "Aa Ii"), [])

    def test_large_drift_still_flagged(self) -> None:
        self.assertIn("line break count changed", translation_issues("a\nb\nc\nd", "abcd"))

    def test_escape_codes_still_enforced(self) -> None:
        self.assertIn("game codes or tags changed", translation_issues("\\V[1] hi", "hello"))

    def test_empty_still_flagged(self) -> None:
        self.assertEqual(translation_issues("a", "  "), ["empty translation"])


class TransportFailureTests(unittest.TestCase):
    """A timeout must not be mistaken for a malformed batch."""

    class _DeadTranslator(CountingTranslator):
        async def _translate_clean_texts(self, clean_texts, source_lang, target_lang):
            self.calls.append(list(clean_texts))
            return []          # nothing came back

    def test_no_response_does_not_fan_out(self) -> None:
        tr = self._DeadTranslator()
        batch = [f"line{i}" for i in range(16)]
        out = _run(tr._translate_with_retry_and_fallback(batch, "ja", "en"))
        self.assertIsNone(out)
        # One attempt, not a cascade of further requests that would time out too.
        self.assertEqual(len(tr.calls), 1)


if __name__ == "__main__":
    unittest.main()
