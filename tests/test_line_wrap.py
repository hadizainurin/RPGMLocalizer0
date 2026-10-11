"""Translated WOLF messages are re-broken so they fit the message window.

Found in the False Myth 2 playtest: "Announcer / "The Judge is our Goddess!
Meltis shall decide! THE Venus Select, OOOOHHH!!!"" ran off the right edge
of the window. The original was 3 lines of ~24 Japanese characters; the model
merged two of them, and nothing re-wrapped the longer English on Save.
"""
import unittest

from src.core.editor.editor_store import EditorStore
from src.core.line_wrap import learn_width, text_width, wrap_text

ANNOUNCER_JA = "アナウンサー\n「ジャッジは我らが女神！メルティスに委ねられる！\n　THE・ヴィーナスセレクトぉおおっ！！！」"
ANNOUNCER_EN = 'Announcer\n"The Judge is our Goddess! Meltis shall decide! THE Venus Select, OOOOHHH!!!"'


class WrapTextTests(unittest.TestCase):
    def test_reported_line_is_split_and_speaker_kept(self):
        out = wrap_text(ANNOUNCER_EN, 50)
        lines = out.split("\n")
        self.assertEqual(lines[0], "Announcer")
        self.assertTrue(all(text_width(l) <= 50 for l in lines), out)
        self.assertEqual(out.replace("\n", " "), ANNOUNCER_EN.replace("\n", " "))

    def test_wrapping_twice_changes_nothing(self):
        once = wrap_text(ANNOUNCER_EN, 40)
        self.assertEqual(wrap_text(once, 40), once)

    def test_short_lines_are_never_joined(self):
        text = "Yes.\nNo.\nMaybe."
        self.assertEqual(wrap_text(text, 50), text)

    def test_codes_take_no_width_and_are_not_cut(self):
        text = "\\c[02]\\f[24]\\A+" + "word " * 9 + "end"   # 48 visible chars
        self.assertEqual(wrap_text(text, 48), text)
        out = wrap_text(text + " \\cself[07] more words here", 30)
        self.assertIn("\\cself[07]", out)
        self.assertIn("\\c[02]\\f[24]\\A+", out.split("\n")[0])

    def test_continuation_keeps_indentation(self):
        out = wrap_text("　they will pin everything on them as the responsible ones", 30)
        self.assertTrue(all(l.startswith("　") for l in out.split("\n")), out)

    def test_one_long_word_is_left_alone(self):
        self.assertEqual(wrap_text("A" * 80, 30), "A" * 80)

    def test_full_width_counts_double(self):
        self.assertEqual(text_width("アナウンサー"), 12)
        self.assertEqual(text_width("\\c[2]abc"), 3)


class LearnWidthTests(unittest.TestCase):
    def test_width_comes_from_the_original_lines(self):
        originals = ["\\f[24]" + "あ" * 28] * 50 + ["\\f[24]" + "あ" * 10] * 50
        width = learn_width(originals)
        self.assertEqual((width.units, width.ref_size), (56, 24))
        self.assertEqual(width.limit_for("\\f[24]x"), 49)
        # A smaller font fits more characters in the same window.
        self.assertGreater(width.limit_for("\\f[17]x"), 49)


class FontSizeTests(unittest.TestCase):
    def test_size_change_after_text_does_not_widen_the_limit(self):
        # Seen in False Myth 2: a \\f[17] footnote on line 3 made the whole
        # message wrap at 75 characters, and line 1 ran off the window.
        from src.core.line_wrap import font_size
        self.assertIsNone(font_size("\\wE[03]デートに最適！\n\\f[17]食べたら"))
        self.assertEqual(font_size("\\c[02]\\f[24]\\A+ははは"), 24)


class ReflowTests(unittest.TestCase):
    """False Myth 2 playtest: a 4-line original became 7 lines once wrapped
    (the model's own breaks each left a short line), and the last line fell
    below the window."""
    ORIG = ("ヴェルカ\n「…でも後悔はしないわ。どんな手を使っても生き延びてやる。\n"
            "\u3000所詮、弱者は淘汰されるのが世の常なの…っ。\n"
            "\u3000無防備なのが悪いんだから…あの女もしかりよ…っ！」")
    EN = ('Velka\n"…But I won\'t regret it. I\'ll survive no matter what it takes.\n'
          'After all, the weak are always weeded out… That\'s just how the world works…\n'
          'It\'s their fault for being defenseless… Just like that woman…!"')

    def test_tall_message_is_reflowed_and_keeps_the_speaker(self):
        from src.core.line_wrap import has_speaker_line
        self.assertTrue(has_speaker_line(self.ORIG))
        plain = wrap_text(self.EN, 53)
        flowed = wrap_text(self.EN, 53, 4, keep_first=True)
        self.assertEqual(plain.count("\n") + 1, 7)
        self.assertEqual(flowed.count("\n") + 1, 5)
        self.assertEqual(flowed.split("\n")[0], "Velka")
        self.assertTrue(all(text_width(l) <= 53 for l in flowed.split("\n")))
        self.assertEqual(wrap_text(flowed, 53, 4, keep_first=True), flowed)   # stable

    def test_message_that_fits_keeps_its_own_breaks(self):
        text = "Yes.\nNo.\nMaybe."
        self.assertEqual(wrap_text(text, 53, 4), text)


class FontShrinkTests(unittest.TestCase):
    LONG = ('"…Sorry, even Jass has never seen a case of heart-sealing before.\n'
            'Needless to say, the arts and drugs that do this to people are the most '
            'forbidden of all taboos… so nobody really studies them, you know.')

    def test_too_tall_message_gets_just_small_enough_font(self):
        from src.core.line_wrap import fit_message
        text, lines, size = fit_message(self.LONG, 53, 4, False, 24, 18)
        self.assertLess(size, 24)
        self.assertGreaterEqual(size, 18)
        self.assertTrue(text.startswith("\\f[%d]" % size))
        self.assertLessEqual(lines, int(4 * 24 / size))

    def test_existing_size_codes_are_scaled(self):
        from src.core.line_wrap import scale_font
        self.assertEqual(scale_font("\\c[2]\\f[24]\\A+Hi\\f[17]note", 24, 20),
                         "\\c[2]\\f[20]\\A+Hi\\f[14]note")

    def test_shrink_is_undone_before_refitting(self):
        from src.core.line_wrap import fit_message, restore_font_codes
        orig = "「…ごめん、ジャスも封心の症例は初めてなんだ。」"
        shrunk, _, _ = fit_message(self.LONG, 53, 4, False, 24, 18)
        self.assertEqual(restore_font_codes(orig, shrunk).count("\\f["), 0)
        again, _, _ = fit_message(restore_font_codes(orig, shrunk), 53, 4, False, 24, 18)
        self.assertEqual(again, shrunk)                      # stable across loads

    def test_size_change_is_not_code_damage(self):
        from src.core.translation_quality import is_damaged_translation
        self.assertFalse(is_damaged_translation("\\c[02]\\f[24]\\A+ははは、そうだね",
                                                "\\c[02]\\f[20]\\A+Hahaha, that's right", "ja", "en"))
        self.assertFalse(is_damaged_translation("「ははは、そうだね」", "\\f[20]\"Hahaha, right\"", "ja", "en"))

    def test_store_pass_shrinks_and_counts(self):
        store = EditorStore(":memory:")
        orig = "「" + "あ" * 28 + "\n" + "い" * 20 + "」"
        store.load_entries({"/g/CommonEvent.dat": [("e/1", orig, "string_op")] +
                            [(f"x/{i}", "\\f[24]" + "う" * 28, "string_op") for i in range(20)]})
        cur = store.conn.cursor()
        cur.execute("UPDATE entries SET translated_text = ?, translation_source = 'auto' "
                    "WHERE json_path = 'e/1'", (self.LONG,))
        store.conn.commit()
        result = store.apply_line_wrap(0, shrink_font=True, min_font=18)
        self.assertEqual((result["shrunk"], result["too_tall"]), (1, 0))
        cur.execute("SELECT translated_text FROM entries WHERE json_path = 'e/1'")
        first = cur.fetchone()[0]
        self.assertTrue(first.startswith("\\f["))
        self.assertEqual(store.apply_line_wrap(0, shrink_font=True, min_font=18)["wrapped"], 0)
        # Turning the option off puts the normal size back.
        store.apply_line_wrap(0, shrink_font=False)
        cur.execute("SELECT translated_text FROM entries WHERE json_path = 'e/1'")
        self.assertNotIn("\\f[", cur.fetchone()[0])


class StoreWrapPassTests(unittest.TestCase):
    def setUp(self):
        self.store = EditorStore(":memory:")
        fp = "/g/Data/BasicData/CommonEvent.dat"
        self.store.load_entries({
            fp: [("e/1", ANNOUNCER_JA, "string_op"),
                 ("e/2", "はい", "choice"),
                 ("e/3", "「" + "あ" * 28 + "」", "string_op")],
            "/g/data/Map001.json": [("m/1", "これは長い台詞です", "dialogue")],
        })
        cur = self.store.conn.cursor()
        long_choice = "Yes, absolutely, I will go with you to the very end of the world"
        for path, text in (("e/1", ANNOUNCER_EN), ("e/2", long_choice), ("m/1", "word " * 30)):
            cur.execute("UPDATE entries SET translated_text = ?, is_modified = 0, "
                        "translation_source = 'auto' WHERE json_path = ?", (text, path))
        self.store.conn.commit()

    def _row(self, path):
        cur = self.store.conn.cursor()
        cur.execute("SELECT * FROM entries WHERE json_path = ?", (path,))
        return dict(cur.fetchone())

    def test_already_saved_translation_is_wrapped_and_marked_unsaved(self):
        result = self.store.apply_line_wrap(50)
        row = self._row("e/1")
        self.assertEqual(result["wrapped"], 1)
        self.assertEqual(row["is_modified"], 1)        # Save will write it
        self.assertEqual(row["translation_source"], "auto")  # not a hand edit
        self.assertTrue(all(text_width(l) <= 50 for l in row["translated_text"].split("\n")))
        # Second pass: nothing left to do.
        self.assertEqual(self.store.apply_line_wrap(50)["wrapped"], 0)

    def test_choices_and_rpg_maker_rows_are_not_touched(self):
        self.store.apply_line_wrap(30)
        self.assertNotIn("\n", self._row("e/2")["translated_text"])
        self.assertNotIn("\n", self._row("m/1")["translated_text"])

    def test_too_tall_message_gets_a_warning_and_loses_it_when_fixed(self):
        cur = self.store.conn.cursor()
        cur.execute("UPDATE entries SET translated_text = ? WHERE json_path = 'e/3'",
                    ("word " * 60,))
        self.store.conn.commit()
        result = self.store.apply_line_wrap(40)
        self.assertEqual(result["too_tall"], 1)
        self.assertIn("More lines than the message window shows", self._row("e/3")["warning_msg"])
        cur.execute("UPDATE entries SET translated_text = 'Short.' WHERE json_path = 'e/3'")
        self.store.conn.commit()
        self.store.apply_line_wrap(40)
        self.assertEqual(self._row("e/3")["has_warning"], 0)

    def test_automatic_width(self):
        result = self.store.apply_line_wrap(0)
        self.assertGreaterEqual(result["limit"], 30)
        self.assertEqual(self._row("e/1")["is_modified"], 1)


if __name__ == "__main__":
    unittest.main()
