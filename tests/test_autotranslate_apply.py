"""End-to-end auto-translate through the real worker, with a local stub engine."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication

from src.backend.editor_backend import AutoTranslateWorker
from src.core.editor.editor_store import EditorStore

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class AutoTranslateResultTests(unittest.TestCase):
    """The pseudo engine mangles the merge separator and adds bracket-like codes,
    so it exercises both recovery paths: the unmerged retry, and a translation
    that still trips the structural check afterwards."""

    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.store.load_entries({
            "Map001.json": [(f"p{i}", t, "dialogue")
                            for i, t in enumerate(["ああ", "いい", "うう"])]
        })
        self.settings = {
            "engine": "pseudo", "source_lang": "ja", "target_lang": "en", "use_cache": False,
        }

    def tearDown(self) -> None:
        self.store.close()

    def _run(self, **kwargs):
        w = AutoTranslateWorker(self.store, self.settings, **kwargs)
        self.seen = []
        w.finished.connect(lambda n, m: self.seen.append((n, m)))
        w.run()
        return self.seen[-1]

    def test_rows_are_written_and_marked_translated(self) -> None:
        count, _msg = self._run(file_filter="all", category_filter="all")
        self.assertEqual(count, 3)
        stats = self.store.get_stats()
        self.assertEqual(stats["translated"], 3)
        self.assertEqual(stats["untranslated"], 0)

    def test_nothing_is_silently_discarded(self) -> None:
        """Rows that still fail the structural check must be kept, not dropped."""
        self._run(file_filter="all", category_filter="all")
        for row in self.store.query_page(page_size=10)[0]:
            self.assertNotEqual(row["translated_text"], row["original_text"])
            self.assertEqual(row["translation_source"], "auto")

    def test_flagged_rows_are_reported(self) -> None:
        _count, msg = self._run(file_filter="all", category_filter="all")
        self.assertIn("review", msg.lower())

    def test_rows_are_unsaved_so_save_will_write_them(self) -> None:
        self._run(file_filter="all", category_filter="all")
        self.assertEqual(self.store.get_stats()["unsaved"], 3)

    def test_category_scope_limits_the_run(self) -> None:
        count, _msg = self._run(file_filter="all", category_filter="system")
        self.assertEqual(count, 0)
        self.assertEqual(self.store.get_stats()["untranslated"], 3)

    def test_second_run_skips_already_translated_rows(self) -> None:
        self._run(file_filter="all", category_filter="all")
        count, _msg = self._run(file_filter="all", category_filter="all")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()


class UpdateEntrySourceTests(unittest.TestCase):
    """update_entry is the write path for BOTH hand edits and the right-click
    translate actions, so it has to be told which one it is."""

    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.store.load_entries({"Map001.json": [("p0", "AA", "dialogue")]})
        self.eid = self.store.query_page(page_size=10)[0][0]["id"]

    def tearDown(self) -> None:
        self.store.close()

    def test_default_is_a_hand_edit(self) -> None:
        self.store.update_entry(self.eid, "typed by me")
        row = self.store.get_entries([self.eid])[0]
        self.assertEqual(row["translation_source"], "manual")
        self.assertEqual(row["manual_wrap"], 1)

    def test_engine_output_is_marked_auto(self) -> None:
        self.store.update_entry(self.eid, "from the engine", source="auto")
        row = self.store.get_entries([self.eid])[0]
        self.assertEqual(row["translation_source"], "auto")
        self.assertEqual(row["manual_wrap"], 0)

    def test_auto_counts_under_translated_not_edited(self) -> None:
        self.store.update_entry(self.eid, "from the engine", source="auto")
        stats = self.store.get_stats()
        self.assertEqual(stats["translated"], 1)
        self.assertEqual(stats["modified"], 0)

    def test_a_later_hand_edit_reclassifies_the_row(self) -> None:
        self.store.update_entry(self.eid, "from the engine", source="auto")
        self.store.update_entry(self.eid, "fixed by me")
        stats = self.store.get_stats()
        self.assertEqual(stats["translated"], 0)
        self.assertEqual(stats["modified"], 1)

    def test_unknown_source_falls_back_to_manual(self) -> None:
        self.store.update_entry(self.eid, "x", source="nonsense")
        self.assertEqual(self.store.get_entries([self.eid])[0]["translation_source"], "manual")

    def test_both_kinds_are_unsaved(self) -> None:
        self.store.update_entry(self.eid, "x", source="auto")
        self.assertEqual(self.store.get_stats()["unsaved"], 1)


class RetranslateModeTests(unittest.TestCase):
    """Normal runs skip finished lines; re-translate deliberately redoes them."""

    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.store.load_entries({
            "Map001.json": [("p0", "ああ", "dialogue"), ("p1", "いい", "dialogue")]
        })
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]
        self.store.bulk_apply_auto_translations([(self.ids[0], "already done")])
        self.settings = {
            "engine": "pseudo", "source_lang": "ja", "target_lang": "en", "use_cache": False,
        }

    def tearDown(self) -> None:
        self.store.close()

    def _run(self, **kwargs):
        w = AutoTranslateWorker(self.store, self.settings, **kwargs)
        out = []
        w.finished.connect(lambda n, m: out.append((n, m)))
        w.run()
        return out[-1]

    def test_default_run_leaves_finished_lines_alone(self) -> None:
        count, _ = self._run(file_filter="all", category_filter="all")
        self.assertEqual(count, 1)
        row = self.store.get_entries([self.ids[0]])[0]
        self.assertEqual(row["translated_text"], "already done")

    def test_retranslate_overwrites_them(self) -> None:
        count, _ = self._run(file_filter="all", category_filter="all", retranslate=True)
        self.assertEqual(count, 2)
        row = self.store.get_entries([self.ids[0]])[0]
        self.assertNotEqual(row["translated_text"], "already done")

    def test_retranslate_does_not_reuse_the_run_memo(self) -> None:
        """Short-circuiting on a remembered translation would make it a no-op."""
        self._run(file_filter="all", category_filter="all", retranslate=True)
        for row in self.store.query_page(page_size=10)[0]:
            self.assertNotEqual(row["translated_text"], row["original_text"])

    def test_counts_reflect_the_mode(self) -> None:
        self.assertEqual(self.store.get_untranslated_count(), 1)
        self.assertEqual(self.store.get_untranslated_count(include_translated=True), 2)

    def test_scope_still_applies_in_retranslate_mode(self) -> None:
        count, _ = self._run(file_filter="all", category_filter="system", retranslate=True)
        self.assertEqual(count, 0)

    def test_rows_stay_marked_auto(self) -> None:
        self._run(file_filter="all", category_filter="all", retranslate=True)
        self.assertEqual(self.store.get_stats()["translated"], 2)
        self.assertEqual(self.store.get_stats()["modified"], 0)
