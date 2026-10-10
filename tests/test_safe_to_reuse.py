"""Stored translations are only replayed (scan, Patch, Save's cache) when safe.

Both failure kinds were found in a real cache from a False Myth 2 run:
- control codes reordered or dropped (written before the masking fix), and
- ~900 "translations" that were the Japanese original with dakuten and symbols
  stripped (です -> てす, ♥ -> ?), read back from files saved while the encoding
  bug downgraded them to CP932.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.translation_quality import (  # noqa: E402
    breaks_game, safe_to_reuse, still_untranslated,
)


class SafeToReuseTests(unittest.TestCase):
    def test_good_translation(self):
        self.assertTrue(safe_to_reuse("\\c[2]\\f[24]\\A+…っ。", "\\c[2]\\f[24]\\A+…Hmph.", "en"))

    def test_code_followed_by_english_is_not_a_changed_code(self):
        # \A+Special used to segment as \A + "+Special".
        self.assertFalse(breaks_game(
            "\\E\\A+特別イベント中\\c[00]", "\\E\\A+Special Event\\c[00]"))

    def test_dropped_code_is_refused(self):
        self.assertFalse(safe_to_reuse(
            "\\c[2]\\f[24]\\A+宣言してやらぁ…！", "\\c[2]\\f[24]I'll declare it…!", "en"))

    def test_stripped_japanese_is_refused(self):
        orig = "もちろん…メメルですよね？きゃは♥"
        degraded = "もちろん...メメルてすよね?きゃは?"
        self.assertTrue(still_untranslated(degraded, "en"))
        self.assertFalse(safe_to_reuse(orig, degraded, "en"))

    def test_ruby_codes_do_not_count_as_japanese(self):
        self.assertFalse(still_untranslated("Within 10 turns \\r[我,わ] will fall!", "en"))

    def test_japanese_target_is_not_judged(self):
        self.assertFalse(still_untranslated("はい", "ja"))

    def test_a_kept_name_in_english_text_is_fine(self):
        self.assertFalse(still_untranslated("Talk to メメル in the plaza tonight.", "en"))


if __name__ == "__main__":
    unittest.main()


class CacheDeleteTests(unittest.TestCase):
    def test_delete_removes_one_entry(self):
        import tempfile
        from src.core.cache import TranslationCache
        with tempfile.TemporaryDirectory() as tmp:
            c = TranslationCache(cache_dir=tmp)
            c.set("はい", "Yes", "ja", "en")
            c.set("いいえ", "No", "ja", "en")
            self.assertTrue(c.delete("はい", "ja", "en"))
            self.assertFalse(c.delete("はい", "ja", "en"))
            c.save()
            again = TranslationCache(cache_dir=tmp)
            self.assertIsNone(again.get("はい", "ja", "en"))
            self.assertEqual(again.get("いいえ", "ja", "en"), "No")
