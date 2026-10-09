"""After saving, the game files hold the translation. The vanilla source text
has to come back from the backups, or the editor shows English as the original."""
import os
import tempfile
import unittest

from src.core.editor.editor_store import EditorStore
from src.utils.backup import BackupManager


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.game = os.path.join(self.dir, "Map001.json")
        with open(self.game, "w", encoding="utf-8") as fh:
            fh.write('{"x": "AA"}')
        self.store = EditorStore(os.path.join(self.dir, "s.db"))
        self.store.load_entries({self.game: [("p0", "AA", "dialogue")]})
        self.eid = self.store.query_page(page_size=10)[0][0]["id"]

    def tearDown(self) -> None:
        self.store.close()

    def _save(self, text):
        """Mimic the save path: back up, then write the translation out."""
        BackupManager().create_backup(self.game)
        with open(self.game, "w", encoding="utf-8") as fh:
            fh.write('{"x": "%s"}' % text)
        self.store.mark_saved([self.game])

    def test_original_survives_save_and_reload(self) -> None:
        self.store.bulk_apply_auto_translations([(self.eid, "Aa-english")])
        self._save("Aa-english")
        self.store.load_entries(
            {self.game: [("p0", "Aa-english", "dialogue")]},
            backup_files={self.game: {"p0": "AA"}},
        )
        row = self.store.query_page(page_size=10)[0][0]
        self.assertEqual(row["original_text"], "AA")
        self.assertEqual(row["translated_text"], "Aa-english")

    def test_without_a_backup_the_translation_becomes_the_source(self) -> None:
        """The failure mode being guarded against - documented, not desired."""
        self.store.bulk_apply_auto_translations([(self.eid, "Aa-english")])
        self._save("Aa-english")
        self.store.load_entries({self.game: [("p0", "Aa-english", "dialogue")]})
        row = self.store.query_page(page_size=10)[0][0]
        self.assertEqual(row["original_text"], "Aa-english")

    def test_marker_survives_the_recovered_reload(self) -> None:
        self.store.bulk_apply_auto_translations([(self.eid, "Aa-english")])
        self._save("Aa-english")
        self.store.load_entries(
            {self.game: [("p0", "Aa-english", "dialogue")]},
            backup_files={self.game: {"p0": "AA"}},
        )
        row = self.store.query_page(page_size=10)[0][0]
        self.assertEqual(row["translation_source"], "auto")
        self.assertEqual(self.store.get_stats()["translated"], 1)

    def test_oldest_backup_is_first(self) -> None:
        """Recovery uses backups[0]; it must be the vanilla copy, not a later save."""
        import time
        bm = BackupManager()
        first = bm.create_backup(self.game)
        with open(self.game, "w", encoding="utf-8") as fh:
            fh.write('{"x": "Aa-english"}')
        time.sleep(1.1)   # the backup name carries a 1-second timestamp
        BackupManager().create_backup(self.game)
        backups = BackupManager().get_backups_for_file(self.game)
        self.assertGreaterEqual(len(backups), 2)
        self.assertEqual(os.path.basename(backups[0]), os.path.basename(first))


class WolfCompanionBackupTests(unittest.TestCase):
    def test_save_backs_up_the_project_schema(self) -> None:
        """A .dat is unparseable without its .project, and saving rewrites it."""
        import inspect
        from src.backend.editor_backend import EditorBackend
        src = inspect.getsource(EditorBackend.saveChanges)
        self.assertIn('.project', src)
        self.assertIn('create_backup(companion)', src)

    def test_extraction_prefers_the_backups_own_schema(self) -> None:
        import inspect
        from src.backend import editor_backend
        src = inspect.getsource(editor_backend._extract_entries_from_backup)
        bak_first = src.index("bak_project)")
        orig_later = src.index("orig_project)")
        self.assertLess(bak_first, orig_later)


if __name__ == "__main__":
    unittest.main()
