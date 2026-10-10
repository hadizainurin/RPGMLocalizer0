"""JSON-array engines: one line per item, consecutive groups, run in parallel.

Payload logs showed ~15 lines merged into one item with |||RPGMSEP_M|||; the
model split on the separators and returned 23 items for 2, the reply was
rejected, and split-and-retry spent ~3 requests per batch.
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication

from src.backend.editor_backend import AutoTranslateWorker
from src.core.editor.editor_store import EditorStore
from src.core.translators.base import TranslationResult
from src.core.translators.services import LocalLLMTranslator

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class _FakeLocal(LocalLLMTranslator):
    def __new__(cls):
        obj = object.__new__(cls)
        obj.calls = []
        obj.active = 0
        obj.max_active = 0
        return obj

    def __init__(self):
        pass

    async def translate_batch(self, reqs, progress_callback=None):
        self.calls.append([r.text for r in reqs])
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        return [TranslationResult(original_text=r.text, translated_text="EN:" + r.text,
                                  source_lang="ja", target_lang="en", success=True) for r in reqs]

    async def close(self):
        pass


class ParallelRequestTests(unittest.TestCase):
    def _run(self, parallel):
        store = EditorStore(":memory:")
        store.load_entries({"Map001.json": [(f"p{i}", f"台詞{i:02d}です", "dialogue") for i in range(40)]})
        fake = _FakeLocal()
        settings = {"engine": "local_llm", "source_lang": "ja", "target_lang": "en",
                    "use_cache": False, "batch_size": 15, "local_llm_parallel": parallel}
        with mock.patch("src.core.translator.create_translator", return_value=fake):
            AutoTranslateWorker(store, settings).run()
        rows = {r["original_text"]: r["translated_text"] for r in store.query_page(page_size=100)[0]}
        store.close()
        return fake, rows

    def test_lines_are_sent_one_per_item_in_groups(self):
        fake, _ = self._run(parallel=1)
        self.assertEqual([len(c) for c in fake.calls], [14, 13, 13])  # balanced, none over 15
        self.assertFalse(any("RPGMSEP" in t for c in fake.calls for t in c))
        # Consecutive lines stay together, in order.
        self.assertEqual(fake.calls[0][:2], ["台詞00です", "台詞01です"])

    def test_parallel_setting_caps_requests_in_flight(self):
        fake, _ = self._run(parallel=2)
        self.assertEqual(fake.max_active, 2)
        fake1, _ = self._run(parallel=1)
        self.assertEqual(fake1.max_active, 1)

    def test_every_row_gets_its_own_translation(self):
        _, rows = self._run(parallel=3)
        for orig, trans in rows.items():
            self.assertEqual(trans, "EN:" + orig)


if __name__ == "__main__":
    unittest.main()


class PageDedupTests(unittest.TestCase):
    def test_a_line_repeated_across_a_page_is_sent_once(self):
        store = EditorStore(":memory:")
        rows = [(f"p{i}", "ロマーリオ" if i % 10 == 0 else f"台詞{i:02d}です", "actor") for i in range(40)]
        store.load_entries({"DataBase.dat": rows})
        fake = _FakeLocal()
        settings = {"engine": "local_llm", "source_lang": "ja", "target_lang": "en",
                    "use_cache": False, "batch_size": 12, "local_llm_parallel": 1}
        with mock.patch("src.core.translator.create_translator", return_value=fake):
            AutoTranslateWorker(store, settings).run()
        sent = [t for c in fake.calls for t in c]
        out = {r["original_text"]: r["translated_text"] for r in store.query_page(page_size=100)[0]}
        store.close()
        self.assertEqual(sent.count("ロマーリオ"), 1)
        self.assertEqual(out["ロマーリオ"], "EN:ロマーリオ")


class BalancedGroupTests(unittest.TestCase):
    def test_no_small_tail_and_slots_finish_together(self):
        from src.backend.editor_backend import _balanced_groups
        sizes = [len(g) for g in _balanced_groups(list(range(100)), 12, 2)]
        self.assertEqual(sum(sizes), 100)
        self.assertEqual(len(sizes) % 2, 0)
        self.assertLessEqual(max(sizes), 12)
        self.assertLessEqual(max(sizes) - min(sizes), 1)

    def test_order_is_kept(self):
        from src.backend.editor_backend import _balanced_groups
        groups = _balanced_groups(list(range(25)), 12, 1)
        self.assertEqual([x for g in groups for x in g], list(range(25)))
