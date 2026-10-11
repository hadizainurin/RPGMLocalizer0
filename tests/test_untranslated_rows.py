"""Rows left Untranslated after a full run (False Myth 2, 2026-10-11).

1. 3028 of the ~3070 rows had nothing to translate ("？？？", "2", pure codes).
   They stayed under Untranslated and were re-checked on every run.
2. Most of the rest failed because the local model mangled the
   |||TXTSEG||| marker (59% of lines that had one). The model now sees
   numbered tokens {1}, {2} instead.
"""
import asyncio
import unittest

from src.core.editor.editor_store import EditorStore
from src.core.text_segmenter import TEXT_SEGMENT_SEPARATOR as SEP, clean_text, reassemble
from src.core.translators.services import (
    LocalLLMTranslator, MARKER_TOKEN_NOTE, OpenAICompatibleTranslator, decode_markers, encode_markers,
)


class MarkerTokenTests(unittest.TestCase):
    def test_round_trip(self):
        clean = f"最後に、{SEP}お魚の品質{SEP}について"
        sent, n = encode_markers(clean)
        self.assertEqual((sent, n), ("最後に、{1}お魚の品質{2}について", 2))
        self.assertEqual(decode_markers("Finally, about {1}fish quality{2}.", n),
                         f"Finally, about {SEP}fish quality{SEP}.")

    def test_model_variations_are_accepted(self):
        self.assertEqual(decode_markers("A {{1}} B [2] C", 2), f"A {SEP} B {SEP} C")
        # Moved by English word order: kept where the model put them.
        self.assertEqual(decode_markers("{2}x{1}", 2), f"{SEP}x{SEP}")

    def test_missing_or_doubled_token_is_not_guessed(self):
        self.assertNotIn(SEP, decode_markers("A {1} B", 2))
        self.assertNotIn(SEP, decode_markers("A {1} B {1} C", 2))

    def test_line_with_literal_brackets_keeps_old_marker(self):
        clean = f"ア[2]{SEP}い"
        self.assertEqual(encode_markers(clean), (clean, 0))

    def test_end_to_end_through_local_llm(self):
        orig = "\\c[05]クリティカル率 \\c[00]\\f[13]＋\\f[17]\\v1[028]\\c[05]％\\c[00]"
        clean, segs = clean_text(orig)
        seen = {}

        async def fake(self, texts, src, tgt):
            seen["sent"] = texts
            return ["Critical Rate {1}+{2}%"]
        tr = LocalLLMTranslator(model="m", base_url="http://localhost:8080/v1")
        orig_method = OpenAICompatibleTranslator._translate_clean_texts
        OpenAICompatibleTranslator._translate_clean_texts = fake
        try:
            out = asyncio.run(tr._translate_clean_texts([clean], "ja", "en"))
        finally:
            OpenAICompatibleTranslator._translate_clean_texts = orig_method
        self.assertNotIn("TXTSEG", seen["sent"][0])
        self.assertEqual(reassemble(out[0], segs),
                         "\\c[05]Critical Rate \\c[00]\\f[13]+\\f[17]\\v1[028]\\c[05]%\\c[00]")

    def test_prompt_explains_tokens(self):
        tr = LocalLLMTranslator(model="m", base_url="http://localhost:8080/v1",
                                system_prompt="Translate.", prompt_mode="override")
        self.assertIn(MARKER_TOKEN_NOTE, tr._build_system_prompt("en", "ja"))


class NoTextRowsTests(unittest.TestCase):
    def setUp(self):
        self.store = EditorStore(":memory:")
        self.store.load_entries({"/g/CommonEvent.dat": [
            ("a", "？？？", "string_op"), ("b", "2", "system"), ("c", "\\c[05]", "string_op"),
            ("d", "こんにちは", "string_op"),
        ]})
        self.store.classify_no_text("ja")

    def test_counted_separately(self):
        stats = self.store.get_stats()
        self.assertEqual((stats["untranslated"], stats["no_text"]), (1, 3))

    def test_not_queued_for_translation(self):
        self.assertEqual(self.store.get_untranslated_count(), 1)

    def test_filters(self):
        _, n_untr = self.store.query_page(status_filter="untranslated")
        _, n_none = self.store.query_page(status_filter="no_text")
        self.assertEqual((n_untr, n_none), (1, 3))


if __name__ == "__main__":
    unittest.main()
