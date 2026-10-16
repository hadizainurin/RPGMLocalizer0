"""The model's misspelled segment markers must be caught like the real one.

False Myth 2, playtest 2026-10-15: the item card showed
    Magic Attack Power |||TXTSEE|| +6
The game text was "Magic Attack Power |||TXTSEE|| \\c[05]\\cself[07] \\cself[21]\\c[00]"
(CommonEvent 197). The 12B model wrote TXTSEE for TXTSEG; the leak gate and the
scrubber only knew TXTSEG, so the row passed every check, survived every load
and was saved into the game. The reply log shows the other spellings the model
produced (TXTSEEG, TXTSE, TXTSEP, TXTSEMNT, TXTSPNT, TXTSESGE, TXTSEEEE,
TXTSEグ ...); the saved game still had 106 such rows (69 database, 37 event),
some half-scrubbed to "||]" or "E||".
"""
import unittest

from src.core.editor.editor_store import EditorStore
from src.core.text_segmenter import clean_text, reassemble
from src.core.translation_quality import (
    breaks_game, is_damaged_translation, safe_to_reuse, translation_issues,
)

STAT_JA = "魔法攻撃力 \\c[05]\\cself[07] \\cself[21]\\c[00]"
STAT_LEAK = "Magic Attack Power |||TXTSEE|| \\c[05]\\cself[07] \\cself[21]\\c[00]"
SEPARATOR = "internal separator left in text"

# Real spellings from llm_payloads/response_1.jsonl and the saved game.
MISSPELLED = [
    "|||TXTSEE||", "|||TXTSEEG|||", "|||TXTSE|", "|||TXTSEP||", "|||TXTSEMNT||",
    "|||TXTSPNT||", "|||TXTSESGE||", "|||TXTSEEEE||", "|||TXTSEグ|", "|||TEXTSEG|||",
    "|||TXTSG|||", "|||TXTSEQ|", "|||TXTSEDE||", "|||TXTSEAG||",
]


class GateTests(unittest.TestCase):
    def test_the_real_item_line_is_caught(self):
        self.assertIn(SEPARATOR, translation_issues(STAT_JA, STAT_LEAK))
        self.assertTrue(breaks_game(STAT_JA, STAT_LEAK))
        self.assertFalse(safe_to_reuse(STAT_JA, STAT_LEAK, "en"))
        self.assertTrue(is_damaged_translation(STAT_JA, STAT_LEAK, "ja", "en"))

    def test_every_misspelling_is_caught(self):
        for marker in MISSPELLED:
            with self.subTest(marker=marker):
                self.assertIn(SEPARATOR, translation_issues("攻撃力 ＋", f"Attack {marker}+"))

    def test_half_scrubbed_pipes_are_caught(self):
        # What the old scrubber left behind in the saved game.
        for text in ("\\c[05]Attack Power [\\c[00]\\font[0]\\f[13]+\\font[0]||]\\c[00]",
                     "Map Number |\nVariable CheckE||\nAction ID",
                     "\\f[13] Remaining \\my[-5] × E|| \\f[16]"):
            with self.subTest(text=text):
                self.assertIn(SEPARATOR, translation_issues("あ\nい", text))

    def test_ordinary_english_is_not_flagged(self):
        for text in ("The text structure is fine", "TEXT SECTION: see the TXT file",
                     "Strength | Magic", "Option A or B"):
            with self.subTest(text=text):
                self.assertNotIn(SEPARATOR, translation_issues("あ", text))

    def test_pipes_the_original_already_has_are_not_flagged(self):
        self.assertNotIn(SEPARATOR, translation_issues("A||B", "A||B!"))


class ReassembleTests(unittest.TestCase):
    def test_leaked_item_line_is_scrubbed(self):
        _, segs = clean_text(STAT_JA)
        out = reassemble("Magic Attack Power |||TXTSEE||", segs)
        for piece in ("TXTS", "|"):
            self.assertNotIn(piece, out)
        self.assertIn("Magic Attack Power", out)
        self.assertNotIn(SEPARATOR, translation_issues(STAT_JA, out))

    def test_misspelled_markers_still_split_in_place(self):
        orig = "\\c[05]攻撃力\\c[00]\\font[0]＋\\font[1]\\v1[028]％"
        _, segs = clean_text(orig)
        self.assertEqual(clean_text(orig)[0], "攻撃力|||TXTSEG|||＋|||TXTSEG|||％")
        out = reassemble("Attack Power|||TXTSEE|||+|||TXTSEP|||%", segs)
        self.assertEqual(out, "\\c[05]Attack Power\\c[00]\\font[0]+\\font[1]\\v1[028]%")

    def test_a_word_glued_to_the_marker_survives(self):
        _, segs = clean_text("\\c[05]防御\\c[00]")
        out = reassemble("|||TXTSEグProtect|||", segs)
        self.assertIn("Protect", out)
        self.assertNotIn("TXTS", out)
        self.assertNotIn("グ", out)

    def test_english_text_is_left_alone(self):
        _, segs = clean_text("\\c[05]説明\\c[00]")
        self.assertEqual(reassemble("The text structure|||TXTSEG|||", segs),
                         "\\c[05]The text structure\\c[00]")


class StrayBetweenCodesTests(unittest.TestCase):
    """Same item card (CommonEvent 197): the model filled the gap between two
    codes with junk, so the game shows "Max HP +_, 6". Real rows."""
    STAT = "\\c[05]\\cself[07] \\cself[21]\\c[00]"

    def test_real_item_card_rows_are_caught(self):
        for ja, en in (("最大HP", "Max HP \\c[05]\\cself[07]_, \\cself[21]\\c[00]"),
                       ("防御力", "Defense power \\c[05]\\cself[07]_, \\cself[21]\\c[00]"),
                       ("クリティカル率", "Critical rate \\c[05]\\cself[07]_\\cself[21]\\c[00]"),
                       ("トリック率", "Trick rate \\c[05]\\cself[07]}\\cself[21]\\c[00]"),
                       ("魔法攻撃力", "Magic Attack Power \\c[05]\\cself[07]|\\cself[21]\\c[00]"),
                       ("マーキング率", "Marking Rate \\c[05]\\cself[07]% \\cself[21]\\c[00]")):
            with self.subTest(en=en):
                orig = f"{ja} {self.STAT}"
                self.assertIn("reply debris in text", translation_issues(orig, en))
                self.assertTrue(breaks_game(orig, en))

    def test_clean_rows_are_not_flagged(self):
        self.assertEqual(translation_issues("バースト力 " + self.STAT,
                                            "Burst Power \\c[05]\\cself[07] \\cself[21]\\c[00]"), [])

    def test_a_gap_the_original_has_is_fine(self):
        orig = "取得AP \\c[05]\\cself[07] \\cself[21]％\\c[00]"
        self.assertEqual(translation_issues(orig, "AP Acquired \\c[05]\\cself[07] \\cself[21]% \\c[00]"), [])
        self.assertEqual(translation_issues("\\c[05]【\\c[00]\\cself[21]", "\\c[05][\\c[00]\\cself[21]"), [])
        self.assertEqual(translation_issues("\\-[07]＋\\-[00]", "\\-[07]+\\-[00]"), [])

    def test_a_doubled_percent_is_caught(self):
        self.assertIn("reply debris in text", translation_issues(
            "APを\\c[06]\\cself[41]％\\c[00]失う", "Lose AP\\c[06]\\cself[41]%%\\c[00]"))


class ReloadTests(unittest.TestCase):
    def test_saved_leaks_are_reset_on_load(self):
        store = EditorStore(":memory:")
        store.load_entries({"/g/CommonEvent.dat": [("e/197", STAT_JA, "string_op"),
                                                    ("e/2", "\\c[2]はい", "string_op")]})
        cur = store.conn.cursor()
        cur.execute("UPDATE entries SET translated_text = ?, translation_source = 'auto', "
                    "is_modified = 0 WHERE json_path = 'e/197'", (STAT_LEAK,))
        cur.execute("UPDATE entries SET translated_text = '\\c[2]Yes', translation_source = 'auto', "
                    "is_modified = 0 WHERE json_path = 'e/2'")
        store.conn.commit()
        self.assertEqual(store.repair_damaged_translations("ja", "en"), 1)
        cur.execute("SELECT json_path, translated_text, is_modified FROM entries ORDER BY json_path")
        rows = [tuple(r) for r in cur.fetchall()]
        self.assertEqual(rows[0], ("e/197", STAT_JA, 1))      # back to Japanese; retranslate, then Save
        self.assertEqual(rows[1][1], "\\c[2]Yes")
        # A second load must not reset anything: no reset loop.
        self.assertEqual(store.repair_damaged_translations("ja", "en"), 0)


if __name__ == "__main__":
    unittest.main()
