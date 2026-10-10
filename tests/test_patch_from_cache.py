"""Patch from Cache fills rows from earlier translations without an engine.

A fresh copy of a game that was translated before is untranslated on disk, but
every line is still in the translation cache. Getting it into the game used to
need a full Start Translation run.
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication

from src.backend.editor_backend import AutoTranslateWorker
from src.core.editor.editor_store import EditorStore

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class _FakeCache:
    def __init__(self, data):
        self.data = data
        self.saved = False

    def get(self, text, source_lang, target_lang):
        return self.data.get(text)

    def set(self, *a):
        raise AssertionError("patch mode must not write to the cache")

    def save(self):
        self.saved = True


class PatchFromCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.store.load_entries({
            "Map001.json": [("p0", "はい", "dialogue"), ("p1", "いいえ", "dialogue"),
                            ("p2", "知らない行", "dialogue")]
        })
        self.cache = _FakeCache({"はい": "Yes", "いいえ": "No"})
        # An engine that must never be built: patch mode sends nothing.
        self.settings = {"engine": "must-not-be-created", "source_lang": "ja",
                         "target_lang": "en", "use_cache": False}

    def tearDown(self) -> None:
        self.store.close()

    def _run(self):
        out = []
        with mock.patch("src.core.cache.get_cache", return_value=self.cache), \
             mock.patch("src.core.translator.create_translator",
                        side_effect=AssertionError("engine created in patch mode")):
            w = AutoTranslateWorker(self.store, self.settings, cache_only=True)
            w.finished.connect(lambda n, m: out.append((n, m)))
            w.run()
        return out[-1]

    def test_cached_lines_are_filled(self) -> None:
        count, _ = self._run()
        self.assertEqual(count, 2)
        texts = {r["original_text"]: r["translated_text"]
                 for r in self.store.query_page(page_size=10)[0]}
        self.assertEqual(texts["はい"], "Yes")
        self.assertEqual(texts["いいえ"], "No")
        self.assertEqual(texts["知らない行"], "知らない行")

    def test_uncached_lines_are_reported(self) -> None:
        _, msg = self._run()
        self.assertIn("Patched 2", msg)
        self.assertIn("1 are not in the cache", msg)

    def test_patched_rows_are_unsaved_so_save_writes_them(self) -> None:
        self._run()
        self.assertEqual(self.store.get_stats()["unsaved"], 2)
        self.assertEqual(self.store.get_stats()["translated"], 2)

    def test_runs_even_when_the_cache_setting_is_off(self) -> None:
        # use_cache=False in settings: patching is the whole point, so it reads anyway.
        count, _ = self._run()
        self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()


class SavedCacheTests(unittest.TestCase):
    """Patch also reads the cache Save writes (raw original -> final text)."""

    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.store.load_entries({"Map001.json": [("p0", "\\c[2]ありがとう\\c[0]", "dialogue")]})
        self.settings = {"engine": "x", "source_lang": "ja", "target_lang": "en"}

    def tearDown(self) -> None:
        self.store.close()

    def test_saved_line_is_restored_exactly(self) -> None:
        saved = _FakeCache({"\\c[2]ありがとう\\c[0]": "\\c[2]Thank you\\c[0]"})
        empty = _FakeCache({})
        out = []
        with mock.patch("src.core.cache.get_cache", return_value=empty), \
             mock.patch("src.core.cache.TranslationCache", return_value=saved):
            w = AutoTranslateWorker(self.store, self.settings, cache_only=True)
            w.finished.connect(lambda n, m: out.append((n, m)))
            w.run()
        self.assertEqual(out[-1][0], 1)
        row = self.store.query_page(page_size=10)[0][0]
        self.assertEqual(row["translated_text"], "\\c[2]Thank you\\c[0]")


class FlaggedTranslationsAreNotCachedTests(unittest.TestCase):
    """A translation kept only because it is the retry pass's last chance is
    flagged for review. Caching it would replay a suspect line everywhere."""

    def test_flagged_rows_never_reach_the_cache(self) -> None:
        store = EditorStore(":memory:")
        store.load_entries({"Map001.json": [(f"p{i}", t, "dialogue")
                                            for i, t in enumerate(["ああ", "いい", "うう"])]})
        written = []

        class _Recorder(_FakeCache):
            def set(self, text, translation, *a):
                written.append((text, translation))

        settings = {"engine": "pseudo", "source_lang": "ja", "target_lang": "en", "use_cache": True}
        out = []
        with mock.patch("src.core.cache.get_cache", return_value=_Recorder({})):
            w = AutoTranslateWorker(store, settings)
            w.finished.connect(lambda n, m: out.append((n, m)))
            w.run()
        store.close()
        # The pseudo engine's output trips the structural check on every line
        # (see test_autotranslate_apply), so all three are flagged.
        self.assertIn("review", out[-1][1].lower())
        self.assertEqual(written, [])


class _DeletableCache(_FakeCache):
    def __init__(self, data):
        super().__init__(data)
        self.deleted = []

    def delete(self, text, source_lang, target_lang):
        self.deleted.append(text)
        return self.data.pop(text, None) is not None


class UnsafeEntriesArePurgedTests(unittest.TestCase):
    """A cached translation that fails the reuse check is deleted, so it is not
    found - and refused - again on every run."""

    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        self.orig = "\\c[2]\\f[24]\\A+宣言してやらぁ…！"
        self.store.load_entries({"Map001.json": [("p0", self.orig, "dialogue")]})
        self.settings = {"engine": "x", "source_lang": "ja", "target_lang": "en"}

    def tearDown(self) -> None:
        self.store.close()

    def _patch(self, saved, run):
        out = []
        with mock.patch("src.core.cache.get_cache", return_value=run), \
             mock.patch("src.core.cache.TranslationCache", return_value=saved):
            w = AutoTranslateWorker(self.store, self.settings, cache_only=True)
            w.finished.connect(lambda n, m: out.append((n, m)))
            w.run()
        return out[-1]

    def test_saved_entry_with_dropped_code_is_deleted(self) -> None:
        saved = _DeletableCache({self.orig: "\\c[2]\\f[24]I'll declare it…!"})
        count, msg = self._patch(saved, _DeletableCache({}))
        self.assertEqual(count, 0)
        self.assertNotIn(self.orig, saved.data)
        self.assertIn("removed from the cache", msg)

    def test_stripped_japanese_entry_is_deleted(self) -> None:
        self.store.close()
        self.store = EditorStore(":memory:")
        orig = "もちろん…メメルですよね？きゃは♥"
        self.store.load_entries({"Map001.json": [("p0", orig, "dialogue")]})
        saved = _DeletableCache({orig: "もちろん...メメルてすよね?きゃは?"})
        self._patch(saved, _DeletableCache({}))
        self.assertEqual(saved.data, {})

    def test_good_entries_are_kept(self) -> None:
        saved = _DeletableCache({self.orig: "\\c[2]\\f[24]\\A+I'll declare it…!"})
        count, _ = self._patch(saved, _DeletableCache({}))
        self.assertEqual(count, 1)
        self.assertIn(self.orig, saved.data)
        self.assertEqual(saved.deleted, [])


class ScanPurgeTests(unittest.TestCase):
    def test_scan_deletes_an_unsafe_cached_translation(self) -> None:
        orig = "もちろん…メメルですよね？"
        cache = _DeletableCache({orig: "もちろん...メメルてすよね?"})
        store = EditorStore(":memory:")
        store.load_entries({"Map001.json": [("p0", orig, "dialogue")]},
                           cache_resolver=cache, target_lang="en", source_lang="ja")
        row = store.query_page(page_size=10)[0][0]
        store.close()
        self.assertEqual(row["translated_text"], orig)
        self.assertEqual(cache.data, {})


class TranslationRunPurgeTests(unittest.TestCase):
    def test_unsafe_cache_hit_is_deleted_and_sent_to_the_engine(self) -> None:
        store = EditorStore(":memory:")
        store.load_entries({"Map001.json": [("p0", "もちろんですよね", "dialogue")]})
        run = _DeletableCache({"もちろんですよね": "もちろんてすよね"})
        out = []
        settings = {"engine": "pseudo", "source_lang": "ja", "target_lang": "en", "use_cache": True}
        with mock.patch("src.core.cache.get_cache", return_value=run):
            w = AutoTranslateWorker(store, settings)
            w.finished.connect(lambda n, m: out.append((n, m)))
            w.run()
        row = store.query_page(page_size=10)[0][0]
        store.close()
        self.assertIn("もちろんですよね", run.deleted)
        self.assertNotEqual(row["translated_text"], "もちろんてすよね")


class ScanFillIsSavedTests(unittest.TestCase):
    """Rows the scan fills from the cache are not in the game file yet. They
    showed as Translated but were not unsaved, so Save - and Patch, which only
    fills Untranslated rows - never wrote them: the game kept the Japanese."""

    def test_cache_filled_rows_are_unsaved(self) -> None:
        cache = _DeletableCache({"はい": "Yes"})
        store = EditorStore(":memory:")
        store.load_entries({"Map001.json": [("p0", "はい", "dialogue"), ("p1", "いいえ", "dialogue")]},
                           cache_resolver=cache, target_lang="en", source_lang="ja")
        stats = store.get_stats()
        changes, _ = store.get_modified_entries()
        store.close()
        self.assertEqual(stats["translated"], 1)
        self.assertEqual(stats["unsaved"], 1)
        self.assertEqual(stats["modified"], 0)  # still "Translated", not "Edited by me"
        self.assertEqual(changes["Map001.json"], {"p0": "Yes"})

    def test_rows_already_in_the_game_file_stay_saved(self) -> None:
        store = EditorStore(":memory:")
        store.load_entries({"Map001.json": [("p0", "Yes", "dialogue")]},
                           backup_files={"Map001.json": {"p0": "はい"}})
        stats = store.get_stats()
        store.close()
        self.assertEqual(stats["translated"], 1)
        self.assertEqual(stats["unsaved"], 0)
