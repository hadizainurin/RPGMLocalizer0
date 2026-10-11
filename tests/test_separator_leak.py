"""The internal segment marker must never reach the game.

False Myth 2, 2026-10-11: for the item text
    \\c[05]前衛トリック成功率【\\c[00]\\font[0]\\f[13]＋\\f[17]...\\c[05]】\\c[00]
the request carried "前衛トリック成功率【|||TXTSEG|||＋|||TXTSEG|||】" and the
local model answered "Front-line Trick Success Rate [|||TXTSEG||+|||TXTSEG|]"
(pipes dropped). The split needed exactly three pipes, so it failed; the
fallback put every code at the end and the half-pipes slipped past the
scrubber. 296 rows reached the game like that, and none failed the gates.
"""
import unittest

import asyncio

from src.core.editor.editor_store import EditorStore
from src.core.text_segmenter import clean_text, parts_match, reassemble
from src.core.translators.base import TranslationRequest
from src.core.translators.services import OpenAICompatibleTranslator
from src.core.translation_quality import breaks_game, safe_to_reuse, translation_issues

TRICK = "\\c[05]前衛トリック成功率【\\c[00]\\font[0]\\f[13]＋\\f[17]\\font[1]\\v1[028]\\font[0]\\c[05]】\\c[00]"
HINDER = ("\\c[05]前衛妨害率 \\c[00]\\font[0]\\f[13]＋\\f[17]\\font[1]\\v1[027]\\font[0]％\\c[05]"
          "\r\n（トリック成功率UP）")


class DroppedPipesTests(unittest.TestCase):
    def test_real_reply_with_dropped_pipes_reassembles_in_place(self):
        clean, segs = clean_text(TRICK)
        self.assertEqual(clean, "前衛トリック成功率【|||TXTSEG|||＋|||TXTSEG|||】")
        out = reassemble("Front-line Trick Success Rate [|||TXTSEG||+|||TXTSEG|]", segs)
        self.assertEqual(out, "\\c[05]Front-line Trick Success Rate [\\c[00]\\font[0]\\f[13]+"
                              "\\f[17]\\font[1]\\v1[028]\\font[0]\\c[05]]\\c[00]")
        self.assertEqual(translation_issues(TRICK, out), [])

    def test_second_real_reply(self):
        _, segs = clean_text(HINDER)
        out = reassemble("Front-line Interference Rate |||TXTSEG|||+|||TXTSEG||%|||TXTSEG|||"
                         "\r\n(Trick Success Rate Up)", segs)
        self.assertNotIn("TXTSEG", out)
        self.assertIn("\\v1[027]\\font[0]%\\c[05]\r\n(Trick", out)

    def test_fallback_never_leaves_marker_pieces(self):
        _, segs = clean_text(TRICK)
        out = reassemble("Rate |TXTSEG plus TXTSEG|| done |||", segs)   # unsplittable
        self.assertNotIn("TXTSEG", out)

    def test_empty_part_is_kept_as_empty(self):
        _, segs = clean_text("\\c[2]はい\\c[0]、\\c[3]いいえ")
        self.assertEqual(reassemble("Yes|||TXTSEG||||||TXTSEG|||No", segs), "\\c[2]Yes\\c[0]\\c[3]No")


class GateTests(unittest.TestCase):
    def test_leaked_marker_is_game_breaking(self):
        leaked = "\\c[05]Eating |||TXTSEG|| will also \\c[05]restore\\c[00]"
        original = "\\c[05]食べたら\\c[05]活力\\c[00]"
        self.assertIn("internal separator left in text", translation_issues(original, leaked))
        self.assertTrue(breaks_game(original, leaked))
        self.assertFalse(safe_to_reuse(original, leaked, "en"))

    def test_marker_in_both_is_not_flagged(self):
        # Run-cache entries are keyed on the cleaned text, which has markers.
        self.assertNotIn("internal separator left in text",
                         translation_issues("あ|||TXTSEG|||い", "a|||TXTSEG|||b"))


class CutShortReplyTests(unittest.TestCase):
    """The bigger bug behind the leak: the LLM layer cleaned the editor's
    already-cleaned text again, found no codes, and kept only the part
    before the first marker. 841 False Myth 2 lines lost their ending."""

    def _engine_reply(self, clean, reply):
        t = OpenAICompatibleTranslator("k", "m", "http://localhost")

        async def fake(batch, src, tgt):
            return [reply for _ in batch]
        t._translate_clean_texts = fake
        res = asyncio.run(t.translate_batch([TranslationRequest(text=clean, source_lang="ja",
                                                                target_lang="en")]))
        return res[0].translated_text

    def test_pre_cleaned_text_comes_back_whole(self):
        clean, segs = clean_text("\\c[2]ダンジョンLV【\\v[5]】")
        out = self._engine_reply(clean, "Dungeon LV [|||TXTSEG|||]")
        self.assertEqual(out, "Dungeon LV [|||TXTSEG|||]")
        self.assertEqual(reassemble(out, segs), "\\c[2]Dungeon LV [\\v[5]]")

    def test_raw_text_is_still_protected_by_the_engine(self):
        out = self._engine_reply("\\c[2]はい", "Yes")
        self.assertEqual(out, "\\c[2]Yes")

    def test_extra_parts_are_not_dropped(self):
        _, segs = clean_text("\\c[2]はい\\c[0]")
        self.assertIn("more", reassemble("Yes|||TXTSEG|||more", segs))

    def test_parts_match(self):
        _, segs = clean_text("\\c[2]ダンジョンLV【\\v[5]】")
        self.assertTrue(parts_match("Dungeon LV [|||TXTSEG|||]", segs))
        self.assertFalse(parts_match("Dungeon LV [", segs))

    def test_rows_from_cut_short_replies_are_reset(self):
        store = EditorStore(":memory:")
        orig = "\\c[2]ダンジョンLV【\\v[5]】"
        store.load_entries({"/g/CommonEvent.dat": [("e/1", orig, "string_op"),
                                                    ("e/2", "\\c[2]はい", "string_op")]})
        cur = store.conn.cursor()
        cur.execute("UPDATE entries SET translated_text = '\\c[2] Dungeon LV \\v[5] [', "
                    "translation_source = 'auto', is_modified = 0 WHERE json_path = 'e/1'")
        cur.execute("UPDATE entries SET translated_text = '\\c[2]Yes', "
                    "translation_source = 'auto', is_modified = 0 WHERE json_path = 'e/2'")
        store.conn.commit()
        replies = {clean_text(orig)[0]: "Dungeon LV ["}
        self.assertEqual(store.reset_cut_short_translations(replies.get), [orig])
        cur.execute("SELECT json_path, translated_text, is_modified FROM entries ORDER BY json_path")
        rows = [tuple(r) for r in cur.fetchall()]
        self.assertEqual(rows[0], ("e/1", orig, 1))          # back to Japanese, Save repairs file
        self.assertEqual(rows[1][1], "\\c[2]Yes")           # single-part line untouched


if __name__ == "__main__":
    unittest.main()
