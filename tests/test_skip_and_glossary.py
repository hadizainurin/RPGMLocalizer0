"""Rules that answer a line without spending a model request."""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication

from src.backend.editor_backend import AutoTranslateWorker
from src.core.editor.editor_store import EditorStore
from src.core.glossary import Glossary

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class GlossaryLookupTests(unittest.TestCase):
    def _glossary(self, terms, case_sensitive=False):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "g.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"terms": terms, "case_sensitive": case_sensitive}, fh,
                      ensure_ascii=False)
        return Glossary(path)

    def test_whole_line_match_returns_the_translation(self) -> None:
        g = self._glossary({"ポーション": "Potion"})
        self.assertEqual(g.lookup_exact("ポーション"), "Potion")

    def test_surrounding_text_is_not_a_whole_line_match(self) -> None:
        """A sentence containing a term still needs real translation."""
        g = self._glossary({"ポーション": "Potion"})
        self.assertIsNone(g.lookup_exact("ポーションを使う"))

    def test_whitespace_is_tolerated(self) -> None:
        g = self._glossary({"Potion": "ポーション"})
        self.assertEqual(g.lookup_exact("  Potion  "), "ポーション")

    def test_case_insensitive_by_default(self) -> None:
        g = self._glossary({"Potion": "X"})
        self.assertEqual(g.lookup_exact("potion"), "X")

    def test_case_sensitive_when_configured(self) -> None:
        g = self._glossary({"Potion": "X"}, case_sensitive=True)
        self.assertIsNone(g.lookup_exact("potion"))

    def test_unknown_and_empty(self) -> None:
        g = self._glossary({"Potion": "X"})
        self.assertIsNone(g.lookup_exact("Elixir"))
        self.assertIsNone(g.lookup_exact("   "))


class WorkerRuleTests(unittest.TestCase):
    TEXTS = ["ああ", "DEBUG_FLAG_01", "ポーション"]

    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.store.load_entries({"Map001.json": [
            (f"p{i}", t, "dialogue") for i, t in enumerate(self.TEXTS)]})
        d = tempfile.mkdtemp()
        self.gloss = os.path.join(d, "g.json")
        with open(self.gloss, "w", encoding="utf-8") as fh:
            json.dump({"terms": {"ポーション": "Potion"},
                       "case_sensitive": False}, fh, ensure_ascii=False)

    def tearDown(self) -> None:
        self.store.close()

    def _run(self, **extra):
        settings = {"engine": "pseudo", "source_lang": "ja", "target_lang": "en",
                    "use_cache": False}
        settings.update(extra)
        w = AutoTranslateWorker(self.store, settings,
                                file_filter="all", category_filter="all")
        seen = []
        w.finished.connect(lambda n, m: seen.append((n, m)))
        w.run()
        return seen[-1]

    def test_skip_pattern_leaves_the_line_untouched(self) -> None:
        _n, _msg = self._run(skip_regex=r"^DEBUG_")
        rows = {r["original_text"]: r for r in self.store.query_page(page_size=10)[0]}
        flagged = rows["DEBUG_FLAG_01"]
        self.assertEqual(flagged["translated_text"], flagged["original_text"])
        self.assertEqual(flagged["translation_source"], "")

    def test_skip_pattern_is_reported(self) -> None:
        _n, msg = self._run(skip_regex=r"^DEBUG_")
        self.assertIn("skipped by pattern", msg)

    def test_other_lines_still_translate(self) -> None:
        self._run(skip_regex=r"^DEBUG_")
        rows = {r["original_text"]: r for r in self.store.query_page(page_size=10)[0]}
        self.assertNotEqual(rows["ああ"]["translated_text"], "ああ")

    def test_invalid_pattern_is_ignored_not_fatal(self) -> None:
        count, _msg = self._run(skip_regex="([unclosed")
        self.assertGreater(count, 0)

    def test_glossary_autofill_answers_without_the_engine(self) -> None:
        _n, msg = self._run(use_glossary=True, glossary_path=self.gloss,
                            glossary_autofill=True)
        rows = {r["original_text"]: r for r in self.store.query_page(page_size=10)[0]}
        self.assertEqual(rows["ポーション"]["translated_text"], "Potion")
        self.assertIn("from the glossary", msg)

    def test_autofill_off_sends_it_to_the_engine(self) -> None:
        _n, msg = self._run(use_glossary=True, glossary_path=self.gloss,
                            glossary_autofill=False)
        self.assertNotIn("from the glossary", msg)

    def test_glossary_rows_count_as_translated(self) -> None:
        self._run(use_glossary=True, glossary_path=self.gloss, glossary_autofill=True)
        self.assertGreaterEqual(self.store.get_stats()["translated"], 1)


if __name__ == "__main__":
    unittest.main()
