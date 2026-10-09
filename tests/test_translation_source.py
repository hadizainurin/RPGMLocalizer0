"""Machine translations and hand edits are counted separately."""
import unittest

from src.core.editor.editor_store import EditorStore


class _Store(EditorStore):
    pass


def _store_with(entries):
    st = EditorStore(":memory:")
    extracted = {"Map001.json": [(f"path{i}", text, "dialogue") for i, text in enumerate(entries)]}
    st.load_entries(extracted)
    return st


class StatusSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store_with(["ああ", "いい", "うう"])
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]

    def tearDown(self) -> None:
        self.store.close()

    def test_fresh_entries_are_untranslated(self) -> None:
        stats = self.store.get_stats()
        self.assertEqual(stats["untranslated"], 3)
        self.assertEqual(stats["translated"], 0)
        self.assertEqual(stats["modified"], 0)

    def test_auto_translation_counts_as_translated_not_modified(self) -> None:
        self.store.bulk_apply_auto_translations([(self.ids[0], "Aa"), (self.ids[1], "Ii")])
        stats = self.store.get_stats()
        self.assertEqual(stats["translated"], 2)
        self.assertEqual(stats["modified"], 0)
        self.assertEqual(stats["untranslated"], 1)

    def test_untranslated_count_actually_drops(self) -> None:
        before = self.store.get_stats()["untranslated"]
        self.store.bulk_apply_auto_translations([(self.ids[0], "Aa")])
        self.assertEqual(self.store.get_stats()["untranslated"], before - 1)

    def test_hand_edit_moves_a_row_from_translated_to_modified(self) -> None:
        self.store.bulk_apply_auto_translations([(self.ids[0], "Aa")])
        self.store.update_entry(self.ids[0], "Aa, properly")
        stats = self.store.get_stats()
        self.assertEqual(stats["translated"], 0)
        self.assertEqual(stats["modified"], 1)

    def test_unsaved_counts_both_kinds(self) -> None:
        self.store.bulk_apply_auto_translations([(self.ids[0], "Aa")])
        self.store.update_entry(self.ids[1], "Ii")
        self.assertEqual(self.store.get_stats()["unsaved"], 2)

    def test_revert_clears_the_marker(self) -> None:
        self.store.bulk_apply_auto_translations([(self.ids[0], "Aa")])
        self.store.revert_entry(self.ids[0])
        stats = self.store.get_stats()
        self.assertEqual(stats["translated"], 0)
        self.assertEqual(stats["modified"], 0)
        self.assertEqual(stats["untranslated"], 3)


class StatusFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store_with(["あ", "い", "う"])
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]
        self.store.bulk_apply_auto_translations([(self.ids[0], "A"), (self.ids[1], "I")])
        self.store.update_entry(self.ids[1], "I, edited")

    def tearDown(self) -> None:
        self.store.close()

    def _ids_for(self, status):
        rows, _ = self.store.query_page(status_filter=status, page_size=10)
        return {r["id"] for r in rows}

    def test_translated_filter_excludes_hand_edits(self) -> None:
        self.assertEqual(self._ids_for("translated"), {self.ids[0]})

    def test_modified_filter_is_hand_edits_only(self) -> None:
        self.assertEqual(self._ids_for("modified"), {self.ids[1]})

    def test_untranslated_filter(self) -> None:
        self.assertEqual(self._ids_for("untranslated"), {self.ids[2]})

    def test_unsaved_filter_covers_both(self) -> None:
        self.assertEqual(self._ids_for("unsaved"), {self.ids[0], self.ids[1]})


if __name__ == "__main__":
    unittest.main()


class LegacyCacheMigrationTests(unittest.TestCase):
    """Opening a cache written before translation_source existed must not crash."""

    LEGACY_SCHEMA = """
    CREATE TABLE file_mtimes (file_path TEXT PRIMARY KEY, mtime REAL);
    CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL, file_name TEXT NOT NULL, json_path TEXT NOT NULL,
        tag TEXT NOT NULL, category TEXT NOT NULL,
        original_text TEXT NOT NULL, translated_text TEXT NOT NULL,
        prev_context TEXT DEFAULT '', next_context TEXT DEFAULT '',
        is_modified INTEGER DEFAULT 0, line_count INTEGER DEFAULT 1,
        has_warning INTEGER DEFAULT 0, warning_msg TEXT DEFAULT '',
        manual_wrap INTEGER DEFAULT 0
    );
    INSERT INTO entries (file_path,file_name,json_path,tag,category,
                         original_text,translated_text,is_modified,manual_wrap)
    VALUES ('m.json','m.json','p1','dialogue','dialogues','AA','Aa',1,0),
           ('m.json','m.json','p2','dialogue','dialogues','II','Ii edited',1,1),
           ('m.json','m.json','p3','dialogue','dialogues','UU','UU',0,0);
    """

    def setUp(self) -> None:
        import sqlite3, tempfile, os
        self.path = os.path.join(tempfile.mkdtemp(), "legacy.db")
        con = sqlite3.connect(self.path)
        con.executescript(self.LEGACY_SCHEMA)
        con.commit()
        con.close()

    def test_opens_without_error(self) -> None:
        store = EditorStore(self.path)
        self.addCleanup(store.close)
        self.assertEqual(store.get_stats()["total"], 3)

    def test_backfill_infers_source(self) -> None:
        store = EditorStore(self.path)
        self.addCleanup(store.close)
        rows = dict(store.conn.execute(
            "SELECT translated_text, translation_source FROM entries"
        ).fetchall())
        self.assertEqual(rows["Aa"], "auto")          # engine output
        self.assertEqual(rows["Ii edited"], "manual")  # manual_wrap was set
        self.assertEqual(rows["UU"], "")               # untranslated

    def test_migration_is_idempotent(self) -> None:
        EditorStore(self.path).close()
        store = EditorStore(self.path)
        self.addCleanup(store.close)
        self.assertEqual(store.get_stats()["translated"], 1)

    def test_fts_trigger_is_scoped_to_indexed_columns(self) -> None:
        """An unscoped AFTER UPDATE trigger rebuilt FTS on every bookkeeping write."""
        store = EditorStore(self.path)
        self.addCleanup(store.close)
        sql = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'entries_au'"
        ).fetchone()[0]
        self.assertIn("UPDATE OF", sql)
        self.assertIn("translated_text", sql)
        self.assertNotIn("is_modified", sql)
