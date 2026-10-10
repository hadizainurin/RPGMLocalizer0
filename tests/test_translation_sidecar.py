"""Exporting the translation dictionary so it can travel with the game."""
import unittest

from src.core.editor.editor_store import EditorStore


def _store(texts=("AA", "II", "UU")):
    st = EditorStore(":memory:")
    st.load_entries({"Map001.json": [(f"p{i}", t, "dialogue") for i, t in enumerate(texts)]})
    return st


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store()
        self.ids = [r["id"] for r in self.store.query_page(page_size=10)[0]]
        self.store.bulk_apply_auto_translations([(self.ids[0], "Aa")])
        self.store.update_entry(self.ids[1], "Ii by hand")

    def tearDown(self) -> None:
        self.store.close()

    def test_exports_only_translated_rows_by_default(self) -> None:
        recs = self.store.export_translations()
        self.assertEqual(len(recs), 2)
        self.assertEqual({r["translated"] for r in recs}, {"Aa", "Ii by hand"})

    def test_records_carry_the_source_marker(self) -> None:
        by_text = {r["translated"]: r for r in self.store.export_translations()}
        self.assertEqual(by_text["Aa"]["source"], "auto")
        self.assertEqual(by_text["Ii by hand"]["source"], "manual")

    def test_keyed_on_file_name_not_absolute_path(self) -> None:
        """So the file applies to a fresh copy of the game elsewhere."""
        rec = self.store.export_translations()[0]
        self.assertEqual(rec["file"], "Map001.json")
        self.assertNotIn("/", rec["file"])
        self.assertIn("original", rec)

    def test_include_untranslated_when_asked(self) -> None:
        self.assertEqual(len(self.store.export_translations(translated_only=False)), 3)


class ImportTests(unittest.TestCase):
    """A fresh, untouched copy of the game gets its translations back."""

    def setUp(self) -> None:
        src = _store()
        ids = [r["id"] for r in src.query_page(page_size=10)[0]]
        src.bulk_apply_auto_translations([(ids[0], "Aa"), (ids[1], "Ii")])
        self.records = src.export_translations()
        src.close()
        self.fresh = _store()

    def tearDown(self) -> None:
        self.fresh.close()

    def test_applies_to_a_fresh_project(self) -> None:
        res = self.fresh.import_translations(self.records)
        self.assertEqual(res["applied"], 2)
        stats = self.fresh.get_stats()
        self.assertEqual(stats["translated"], 2)
        self.assertEqual(stats["unsaved"], 2)

    def test_source_mismatch_is_refused(self) -> None:
        """A sidecar from a different build must not write onto the wrong line."""
        bad = [dict(r, original="SOMETHING ELSE") for r in self.records]
        res = self.fresh.import_translations(bad)
        self.assertEqual(res["applied"], 0)
        self.assertEqual(res["mismatched"], 2)

    def test_unknown_rows_are_skipped_not_fatal(self) -> None:
        res = self.fresh.import_translations(
            self.records + [{"file": "Nope.json", "path": "x", "translated": "y"}])
        self.assertEqual(res["applied"], 2)
        self.assertEqual(res["skipped"], 1)

    def test_existing_translations_are_kept_unless_overwrite(self) -> None:
        ids = [r["id"] for r in self.fresh.query_page(page_size=10)[0]]
        self.fresh.update_entry(ids[0], "mine")
        self.assertEqual(self.fresh.import_translations(self.records)["applied"], 1)
        self.assertEqual(
            self.fresh.get_entries([ids[0]])[0]["translated_text"], "mine")

    def test_overwrite_replaces_them(self) -> None:
        ids = [r["id"] for r in self.fresh.query_page(page_size=10)[0]]
        self.fresh.update_entry(ids[0], "mine")
        self.assertEqual(
            self.fresh.import_translations(self.records, overwrite=True)["applied"], 2)
        self.assertEqual(self.fresh.get_entries([ids[0]])[0]["translated_text"], "Aa")

    def test_round_trip_is_lossless(self) -> None:
        self.fresh.import_translations(self.records)
        again = {r["path"]: r["translated"] for r in self.fresh.export_translations()}
        before = {r["path"]: r["translated"] for r in self.records}
        self.assertEqual(again, before)

    def test_imported_rows_are_unsaved_so_save_patches_the_game(self) -> None:
        self.fresh.import_translations(self.records)
        changes, _ = self.fresh.get_modified_entries()
        flat = {v for f in changes.values() for v in f.values()}
        self.assertEqual(flat, {"Aa", "Ii"})


if __name__ == "__main__":
    unittest.main()


class SlotRegistrationTests(unittest.TestCase):
    """A QML button can only call a slot Qt actually registered.

    Returning a plain dict from an undecorated method, or a result type QML
    cannot marshal, makes the button look dead with no error anywhere.
    """

    def test_slots_are_registered_with_the_expected_signatures(self) -> None:
        from src.backend.editor_backend import EditorBackend
        mo = EditorBackend.staticMetaObject
        sigs = {mo.method(i).methodSignature().data().decode()
                for i in range(mo.methodCount())}
        self.assertIn("exportTranslations(QString,bool)", sigs)
        self.assertIn("importTranslations(QString,bool)", sigs)
        self.assertIn("defaultSidecarPath()", sigs)

    def test_results_are_qml_readable_dicts(self) -> None:
        import os, tempfile, logging
        from unittest.mock import MagicMock
        from src.backend.editor_backend import EditorBackend

        d = tempfile.mkdtemp()
        be = EditorBackend.__new__(EditorBackend)
        be.logger = logging.getLogger("t")
        be._store = _store()
        ids = [r["id"] for r in be._store.query_page(page_size=10)[0]]
        be._store.bulk_apply_auto_translations([(ids[0], "Aa")])
        be.settings_backend = MagicMock()
        be.settings_backend.get_dict.return_value = {"source_lang": "ja", "target_lang": "en"}
        be.app_backend = MagicMock()
        be.app_backend.projectPath = d
        be._refresh_page = lambda: None
        be._refresh_stats = lambda: None
        be.hasUnsavedChangesChanged = MagicMock()

        res = EditorBackend.exportTranslations(be, "", True)
        for key in ("ok", "message", "count"):
            self.assertIn(key, res, f"QML reads res.{key}")
        self.assertTrue(res["ok"])
        self.assertTrue(os.path.isfile(res["path"]))

        res2 = EditorBackend.importTranslations(be, res["path"], True)
        for key in ("ok", "message", "count"):
            self.assertIn(key, res2)
        be._store.close()

    def test_missing_file_returns_a_message_not_an_exception(self) -> None:
        import logging
        from unittest.mock import MagicMock
        from src.backend.editor_backend import EditorBackend
        be = EditorBackend.__new__(EditorBackend)
        be.logger = logging.getLogger("t")
        be._store = _store()
        be.settings_backend = MagicMock()
        be.settings_backend.get_dict.return_value = {}
        be.app_backend = MagicMock()
        be.app_backend.projectPath = "/nope/not/here"
        res = EditorBackend.importTranslations(be, "", False)
        self.assertFalse(res["ok"])
        self.assertIn("No translation file", res["message"])
        be._store.close()
