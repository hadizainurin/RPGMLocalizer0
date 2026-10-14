"""Database fields that hold lookup keys are never translated.

Found in the False Myth 2 playtest: the game stopped with
"音声ファイル読み込みエラー  サウンド:ファイル「Data/cvRouge/B Rouge15_1.ogg」が見つかりません".
The party-member table has a field 呼び出し名v2 holding "Bルージュ"; the game
builds the voice file name from it ("Data/cvRouge/" + "Bルージュ" + "15_1.ogg").
The app translated the value to "B Rouge", so the file was not found.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.editor.editor_store import STORE_VERSION, EditorStore  # noqa: E402
from src.core.parsers.base import ASSET_KEY_TAG  # noqa: E402
from src.core.parsers.wolf_binary import DataRecord, DbType, Field, WolfDatabase  # noqa: E402
from src.core.parsers.wolf_parser import WolfParser, is_key_field  # noqa: E402

PRE_V35_DAT = 0xC3
KEY_PATH = "types/0/data/0/string_values/1"
NAME_PATH = "types/0/data/0/string_values/0"


def _party_db(key_value: str = "Bルージュ", name: str = "ルージュ", key_field: str = "呼び出し名v2") -> WolfDatabase:
    fields = [Field(name="名前", index_info=2000), Field(name=key_field, index_info=2001)]
    t = DbType(
        name="パーティメンバー", fields=fields,
        data=[DataRecord(name=name, int_values=[], string_values=[name, key_value])],
        description="", field_type_list_size=len(fields),
    )
    return WolfDatabase([t], version=PRE_V35_DAT, is_utf8=True)


def _write(directory: str, db: WolfDatabase) -> str:
    dat = os.path.join(directory, "DataBase.dat")
    db.write(os.path.join(directory, "DataBase.project"), dat)
    return dat


class KeyFieldRuleTests(unittest.TestCase):
    def test_key_words_match_fields_that_name_files_or_calls(self):
        for name in ("呼び出し名v2", "呼び出し名v", "cvフォルダ", "ファイル名", "画像名"):
            self.assertTrue(is_key_field(name), name)

    def test_names_and_descriptions_are_not_keys(self):
        for name in ("名前", "キャラ名", "説明文", "チュートリアル名", "依頼内容", "M用キャラ説明"):
            self.assertFalse(is_key_field(name), name)

    def test_extra_words_extend_the_rule(self):
        self.assertFalse(is_key_field("識別X"))
        self.assertTrue(is_key_field("識別X", ["識別X"]))


class ParserTests(unittest.TestCase):
    def test_key_value_is_listed_not_extracted(self):
        with tempfile.TemporaryDirectory() as d:
            dat = _write(d, _party_db())
            parser = WolfParser()
            entries = parser.extract_text(dat)
        self.assertEqual([(p, t) for p, t, _ in entries], [("types/0/data/0/name", "ルージュ"),
                                                           (NAME_PATH, "ルージュ")])
        self.assertEqual(parser._listed_entries, [(KEY_PATH, "Bルージュ", ASSET_KEY_TAG)])

    def test_listing_is_reset_for_every_file(self):
        with tempfile.TemporaryDirectory() as d:
            dat = _write(d, _party_db())
            parser = WolfParser()
            parser.extract_text(dat)
            parser.extract_text(os.path.join(d, "missing.dat"))
        self.assertEqual(parser._listed_entries, [])

    def test_extra_key_field_words_from_settings(self):
        with tempfile.TemporaryDirectory() as d:
            dat = _write(d, _party_db(key_field="識別X"))
            self.assertEqual(WolfParser().extract_text(dat)[-1][0], KEY_PATH)       # translated
            parser = WolfParser(key_field_words=["識別X"])
            parser.extract_text(dat)
        self.assertEqual(len(parser._listed_entries), 1)


class StoreTests(unittest.TestCase):
    FILE = "/g/Data/BasicData/DataBase.dat"

    def _store(self, text: str, original: str = "Bルージュ", cache=None) -> EditorStore:
        store = EditorStore(":memory:")
        store.load_entries({self.FILE: [(KEY_PATH, text, ASSET_KEY_TAG)]},
                           backup_files={self.FILE: {KEY_PATH: original}},
                           cache_resolver=cache, target_lang="en", source_lang="ja")
        store.classify_no_text("ja")
        return store

    def test_translated_key_is_restored_and_unsaved(self):
        store = self._store("B Rouge")
        row = store.conn.execute("SELECT * FROM entries").fetchone()
        self.assertEqual((row["original_text"], row["translated_text"]), ("Bルージュ", "Bルージュ"))
        self.assertEqual(row["is_modified"], 1)            # Save writes the original back
        self.assertEqual(store.last_load_restored_keys, 1)

    def test_untouched_key_is_not_marked_unsaved(self):
        store = self._store("Bルージュ")
        row = store.conn.execute("SELECT * FROM entries").fetchone()
        self.assertEqual(row["is_modified"], 0)
        self.assertEqual(store.last_load_restored_keys, 0)

    def test_key_is_never_queued_for_translation(self):
        store = self._store("Bルージュ")
        self.assertEqual(store.get_untranslated_count(), 0)
        self.assertEqual(store.get_stats()["no_text"], 1)
        self.assertEqual(store.get_untranslated_batch(), [])

    def test_engine_output_and_imports_cannot_overwrite_a_key(self):
        store = self._store("Bルージュ")
        entry_id = store.conn.execute("SELECT id FROM entries").fetchone()["id"]
        self.assertEqual(store.bulk_apply_auto_translations([(entry_id, "B Rouge")]), 0)
        result = store.import_translations([{"file": "DataBase.dat", "path": KEY_PATH,
                                             "original": "Bルージュ", "translated": "B Rouge"}])
        self.assertEqual(result["applied"], 0)
        row = store.conn.execute("SELECT translated_text FROM entries").fetchone()
        self.assertEqual(row["translated_text"], "Bルージュ")

    def test_stale_cached_translation_is_forgotten(self):
        class Cache:
            deleted = []

            def get(self, *a):
                return "B Rouge"

            def delete(self, text, source, target):
                self.deleted.append((text, source, target))

        cache = Cache()
        self._store("B Rouge", cache=cache)
        self.assertIn(("Bルージュ", "ja", "en"), cache.deleted)

    def test_store_version_forces_a_rescan_of_older_databases(self):
        # Rows saved by an earlier version carry the translated key as ordinary
        # text; only a rescan can turn them into key rows.
        self.assertGreaterEqual(STORE_VERSION, 5)


class SaveRoundTripTests(unittest.TestCase):
    def test_save_puts_the_original_key_back_and_keeps_the_translated_name(self):
        with tempfile.TemporaryDirectory() as d:
            dat = _write(d, _party_db(key_value="B Rouge", name="Rouge"))   # what the game holds now
            parser = WolfParser()
            entries = parser.extract_text(dat) + parser._listed_entries
            store = EditorStore(":memory:")
            store.load_entries({dat: entries},
                               backup_files={dat: {KEY_PATH: "Bルージュ", NAME_PATH: "ルージュ",
                                                   "types/0/data/0/name": "ルージュ"}},
                               target_lang="en", source_lang="ja")
            changes, _ = store.get_modified_entries()
            self.assertEqual(changes[dat], {KEY_PATH: "Bルージュ"})
            data = WolfParser().apply_translation(dat, changes[dat])
            out = os.path.join(d, "out.dat")
            with open(out, "wb") as fh:
                fh.write(data)
            back = WolfDatabase.read(os.path.join(d, "DataBase.project"), out)
        record = back.types[0].data[0]
        self.assertEqual(record.string_values, ["Rouge", "Bルージュ"])


if __name__ == "__main__":
    unittest.main()
