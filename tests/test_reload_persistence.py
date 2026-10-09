"""State must survive closing the app and reopening the project."""
import os
import tempfile
import unittest

from src.core.editor.editor_store import EditorStore


class ReloadTests(unittest.TestCase):
    """A rescan rebuilds every row from the game files; markers must carry over."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "store.db")
        self.extracted = {
            "Map001.json": [("p0", "AA", "dialogue"),
                            ("p1", "II", "dialogue"),
                            ("p2", "UU", "dialogue")]
        }
        store = EditorStore(self.db)
        store.load_entries(self.extracted)
        ids = [r["id"] for r in store.query_page(page_size=10)[0]]
        store.bulk_apply_auto_translations([(ids[0], "Aa")])   # machine
        store.update_entry(ids[1], "Ii by hand")               # hand edit
        store.close()

    def _reload(self, extracted=None):
        """Reopen the same cache and rescan, as a fresh app session would."""
        store = EditorStore(self.db)
        store.load_entries(extracted or self.extracted)
        return store

    def test_markers_survive_a_rescan(self) -> None:
        store = self._reload()
        self.addCleanup(store.close)
        rows = {r["translated_text"]: r["translation_source"]
                for r in store.query_page(page_size=10)[0]}
        self.assertEqual(rows["Aa"], "auto")
        self.assertEqual(rows["Ii by hand"], "manual")

    def test_counts_are_not_reset_to_untranslated(self) -> None:
        """The reported symptom: everything looked untouched after reopening."""
        store = self._reload()
        self.addCleanup(store.close)
        stats = store.get_stats()
        self.assertEqual(stats["translated"], 1)
        self.assertEqual(stats["modified"], 1)
        self.assertEqual(stats["untranslated"], 1)

    def test_status_filters_still_work_after_reload(self) -> None:
        store = self._reload()
        self.addCleanup(store.close)
        translated, _ = store.query_page(status_filter="translated", page_size=10)
        edited, _ = store.query_page(status_filter="modified", page_size=10)
        self.assertEqual([r["translated_text"] for r in translated], ["Aa"])
        self.assertEqual([r["translated_text"] for r in edited], ["Ii by hand"])

    def test_unsaved_edits_still_carry_over(self) -> None:
        store = self._reload()
        self.addCleanup(store.close)
        texts = {r["translated_text"] for r in store.query_page(page_size=10)[0]}
        self.assertIn("Ii by hand", texts)
        self.assertIn("Aa", texts)

    def test_untouched_rows_stay_blank(self) -> None:
        store = self._reload()
        self.addCleanup(store.close)
        rows = {r["translated_text"]: r["translation_source"]
                for r in store.query_page(page_size=10)[0]}
        self.assertEqual(rows["UU"], "")

    def test_new_rows_in_a_changed_file_default_to_blank(self) -> None:
        extended = {
            "Map001.json": self.extracted["Map001.json"] + [("p3", "EE", "dialogue")]
        }
        store = self._reload(extended)
        self.addCleanup(store.close)
        rows = {r["translated_text"]: r["translation_source"]
                for r in store.query_page(page_size=10)[0]}
        self.assertEqual(rows["EE"], "")
        self.assertEqual(rows["Aa"], "auto")


if __name__ == "__main__":
    unittest.main()
