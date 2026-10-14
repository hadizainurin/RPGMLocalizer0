"""Corrupt lines found in the translated False Myth 2 files (2026-10-11).

A "repair" fallback in the reply parser turned broken JSON into wrong
pieces: the key "t" as a line, '"]}```  (Note: ...' glued to a line,
neighbouring lines merged. The parser is now strict, and these shapes are
caught on load and refused from the cache.
"""
import unittest

from src.core.translation_quality import is_damaged_translation, safe_to_reuse, translation_issues
from src.core.translators.services import OpenAICompatibleTranslator as T


class StrictParserTests(unittest.TestCase):
    def test_fenced_reply_with_note_is_read_exactly(self):
        raw = '```json\n{"t": ["A", "B"]}\n```\n(Note: The JSON is formatted for readability)'
        self.assertEqual(T._parse_translations(raw), ["A", "B"])

    def test_broken_json_is_a_failed_reply_not_a_guess(self):
        raw = '```json\n{"t": ["\\"…H-honki ka?", \\"「…Sō ka.」", "\\"Hai…\\""]'
        self.assertIsNone(T._parse_translations(raw))

    def test_non_string_items_rejected(self):
        self.assertIsNone(T._parse_translations('{"t": ["a", null]}'))


class CorruptLineGateTests(unittest.TestCase):
    CASES = [
        ("\\c[02]\\f[24]\\A+完全な言いがかりよ…、私見てたもん。", "\\c[02]\\f[24]\\A+\n"),
        ("「大丈夫。絶対、一人になんかしないよ」", "t"),
        ("\\c[2]\\f[24]\\A+でもさ…よくここがわかったね？\n養護施設としてカモフラージュされてるのに", "\\c[2]\\f[24]\\A+ and "),
        ("\\c[05]HP\\c[00]を全回復する", "\\c[05]Recovers all HP\\c[00]}"),
        ("「ぐっ…ぅっ…！！」", '"Guh… ugh…!!"]}```  *(12 lines total, matching input)*'),
        # The model's own checklist pasted into a line, with no JSON around it
        # (event 777 of the saved game).
        ("\\c[2]\\f[24]\\A+学徒にセルナディオ一族がいんのか！？",
         "\\c[2]\\f[24]\\A+.)   (Engine codes unchanged: \\n.)   (No filename translation: .png, .ogg.)   "
         "(All constraints met.)   (Adult tone maintained.)   (JSON format verified.)"),
    ]

    def test_reset_on_load_and_refused_from_cache(self):
        for orig, bad in self.CASES:
            with self.subTest(bad=bad):
                self.assertTrue(is_damaged_translation(orig, bad, "ja", "en"))
                self.assertFalse(safe_to_reuse(orig, bad, "en"))

    def test_good_lines_pass(self):
        for orig, good in (("「っ！！！？」", '"!!!?"'), ("はい", "Yes"),
                           ("\\c[05]HP\\c[00]を全回復する", "\\c[05]HP\\c[00] fully restored"),
                           ("「大丈夫。絶対、一人になんかしないよ」", '"It\'s okay. I won\'t leave you alone."')):
            with self.subTest(good=good):
                self.assertEqual(translation_issues(orig, good), [])
                self.assertFalse(is_damaged_translation(orig, good, "ja", "en"))


if __name__ == "__main__":
    unittest.main()
