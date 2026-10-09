"""Re-translate and restore across a multi-row selection."""
import unittest

from src.core.editor.editor_store import EditorStore


def _store_with(texts):
    st = EditorStore(":memory:")
    st.load_entries({"Map001.json": [(f"p{i}", t, "dialogue") for i, t in enumerate(texts)]})
    return st


class RevertEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store_with(["AA", "II", "UU"])
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]
        self.store.bulk_apply_auto_translations([(i, f"T{i}") for i in self.ids])

    def tearDown(self) -> None:
        self.store.close()

    def test_restores_text_and_clears_flags(self) -> None:
        self.assertEqual(self.store.revert_entries(self.ids[:2]), 2)
        rows = {r["id"]: r for r in self.store.get_entries(self.ids)}
        for i in self.ids[:2]:
            self.assertEqual(rows[i]["translated_text"], rows[i]["original_text"])
            self.assertEqual(rows[i]["translation_source"], "")
            self.assertEqual(rows[i]["is_modified"], 0)
        self.assertEqual(rows[self.ids[2]]["translation_source"], "auto")

    def test_stats_move_back_to_untranslated(self) -> None:
        self.store.revert_entries(self.ids)
        stats = self.store.get_stats()
        self.assertEqual(stats["untranslated"], 3)
        self.assertEqual(stats["translated"], 0)
        self.assertEqual(stats["unsaved"], 0)

    def test_empty_list_is_a_no_op(self) -> None:
        self.assertEqual(self.store.revert_entries([]), 0)

    def test_unknown_ids_are_skipped(self) -> None:
        self.assertEqual(self.store.revert_entries([999999]), 0)

    def test_restore_then_retranslate_round_trip(self) -> None:
        """Restoring must leave the row eligible for translation again."""
        self.store.revert_entries([self.ids[0]])
        self.store.bulk_apply_auto_translations([(self.ids[0], "fresh")])
        row = self.store.get_entries([self.ids[0]])[0]
        self.assertEqual(row["translated_text"], "fresh")
        self.assertEqual(row["translation_source"], "auto")


class GetEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store_with(["AA", "II", "UU"])
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]

    def tearDown(self) -> None:
        self.store.close()

    def test_preserves_caller_order(self) -> None:
        wanted = [self.ids[2], self.ids[0]]
        self.assertEqual([r["id"] for r in self.store.get_entries(wanted)], wanted)

    def test_empty_input(self) -> None:
        self.assertEqual(self.store.get_entries([]), [])


class RetranslateTargetsTests(unittest.TestCase):
    """A re-translate must not skip rows that already hold a translation."""

    def setUp(self) -> None:
        self.store = _store_with(["AA", "II"])
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]

    def tearDown(self) -> None:
        self.store.close()

    def test_translated_rows_are_not_in_the_untranslated_queue(self) -> None:
        self.store.bulk_apply_auto_translations([(self.ids[0], "done")])
        queued = {r["id"] for r in self.store.get_untranslated_batch(limit=10)}
        self.assertNotIn(self.ids[0], queued)
        self.assertIn(self.ids[1], queued)

    def test_but_they_can_still_be_overwritten_directly(self) -> None:
        self.store.bulk_apply_auto_translations([(self.ids[0], "first")])
        self.store.bulk_apply_auto_translations([(self.ids[0], "second")])
        self.assertEqual(self.store.get_entries([self.ids[0]])[0]["translated_text"], "second")


if __name__ == "__main__":
    unittest.main()
