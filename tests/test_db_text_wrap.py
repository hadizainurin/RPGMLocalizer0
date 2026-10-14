"""Multi-line database text is wrapped to the width of its own field.

Found in the False Myth 2 playtest: the battle tutorial (database type
チュートリアル管理, field 説明文) came back from the model as one long
paragraph and ran off the right edge of the tutorial window, because the
word-wrap only covered event messages. The author had broken every Japanese
tutorial text by hand to fit that window, so the widest Japanese line of the
field is the window's width.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backend.editor_backend import _wrap_message  # noqa: E402
from src.core.editor.editor_store import EditorStore  # noqa: E402
from src.core.line_wrap import (  # noqa: E402
    MIN_DB_GROUP, MIN_DB_WIDTH, db_field_key, fit_db_text, is_db_text, learn_db_windows, text_width,
)

FILE = "/g/Data/BasicData/DataBase.dat"
TUTORIAL_JA = [
    ("さぁ！ルージュ様の攻撃のターンです！\r\n攻撃は\\c[05]「↑、←、↓キー」+「Zキー」\\c[00]で行います。\r\n"
     "技を使用すると\\c[05]SP\\c[00]を消費し、SPの許す限り\r\n\\c[05]何度でも攻撃できます\\c[00]！（画面下のSPを確認してね♥）\r\n\r\n"
     "また、それぞれの方向キーとの組み合わせで\r\n\\c[05]性能の異なる技\\c[00]を使えますけど、\r\nこんな雑魚相手で気にする必要はないですわ♪\r\n\r\n"),
    ("\\c[05]同じ技\\c[00]を使うたび、０→\\c[01]１\\c[00]→\\c[01]２\\c[00]と、次に\\c[05]SP\\c[00]を消費する\r\n"
     "数値、いわゆる\\c[05]技コスト\\c[00]が増えちゃいますが…。\r\n（初期値が１の技もあるため注意！）\r\n"),
    ("ルージュ様なら、そのターンの\\c[05]②敵の行動\\c[00]や\r\n次のターンの\\c[05]③大まかな行動\\c[00]まで予測できます。\r\n"),
]
# What the model returned for the first one: its line breaks are gone.
TUTORIAL_EN = ('Now then! It\'s Rouge\'s turn to attack! You\'ll perform \\c[05] the attack with the "↑, ←, ↓ keys" + '
               '"Z \\c[00] key". Using skills consumes SP, and you can \\c[05] attack as many times as \\c[00] your SP '
               'allows! (Check the SP at the \\c[05] bottom of the screen ♥)\n\nAlso, combining \\c[00] each direction '
               'key with the Z key allows you to use skills with different \\c[05] performance characteristics, but '
               '\\c[00] there\'s no need to worry about that with these weaklings♪')


def _path(record: int, field: int = 0, type_index: int = 49) -> str:
    return f"types/{type_index}/data/{record}/string_values/{field}"


class IsDbTextTests(unittest.TestCase):
    def test_multi_line_database_value(self):
        self.assertTrue(is_db_text(FILE, _path(1), "system", TUTORIAL_JA[0]))

    def test_single_line_values_are_left_alone(self):
        self.assertFalse(is_db_text(FILE, _path(1), "system", "ロングソード"))
        self.assertFalse(is_db_text(FILE, _path(1), "system", "一行だけ\r\n"))    # only a trailing break

    def test_names_keys_and_events_are_not_database_text(self):
        multi = "一行目\r\n二行目"
        self.assertFalse(is_db_text(FILE, "types/49/data/1/name", "system", multi))
        self.assertFalse(is_db_text(FILE, _path(1), "asset_key", multi))
        self.assertFalse(is_db_text("/g/Data/BasicData/CommonEvent.dat", "events/1/commands/2/string_args/0",
                                    "dialogue", multi))
        self.assertFalse(is_db_text("/g/Data/MapData/Map001.mps", "events/1/pages/0/commands/2/string_args/0",
                                    "dialogue", multi))


class LearnWindowTests(unittest.TestCase):
    def _items(self, texts, type_index=49):
        return [(db_field_key(FILE, _path(i, 0, type_index)), t) for i, t in enumerate(texts)]

    def test_window_is_the_widest_japanese_line_of_the_field(self):
        windows = learn_db_windows(self._items(TUTORIAL_JA))
        window = windows[db_field_key(FILE, _path(0))]
        widest = max(text_width(l) for t in TUTORIAL_JA for l in t.replace("\r\n", "\n").split("\n"))
        self.assertEqual(window.width.units, widest)
        self.assertEqual(window.limit_for(TUTORIAL_JA[0]), int(widest * 0.89))
        self.assertEqual(window.max_lines, 8)          # trailing blank lines do not count

    def test_short_lines_never_make_a_very_narrow_window(self):
        short = ["あ" * 10 + "\n" + "い" * 10] * 3
        window = learn_db_windows(self._items(short))[db_field_key(FILE, _path(0))]
        self.assertEqual(window.limit_for(short[0]), MIN_DB_WIDTH)

    def test_a_field_with_too_few_values_is_not_trusted(self):
        windows = learn_db_windows(self._items(TUTORIAL_JA[:MIN_DB_GROUP - 1]))
        self.assertEqual(windows, {})

    def test_fields_are_learned_separately(self):
        wide = ["あ" * 30 + "\n" + "い" * 30] * 3
        narrow = ["あ" * 8 + "\n" + "い" * 8] * 3
        windows = learn_db_windows(self._items(wide, 1) + self._items(narrow, 2))
        self.assertGreater(windows[db_field_key(FILE, _path(0, 0, 1))].width.units,
                           windows[db_field_key(FILE, _path(0, 0, 2))].width.units)


class FitDbTextTests(unittest.TestCase):
    LIMIT = 49

    def test_reported_tutorial_is_wrapped_inside_its_window(self):
        text, lines = fit_db_text(TUTORIAL_EN, TUTORIAL_JA[0], self.LIMIT, 11)
        visible = text.replace("\r\n", "\n").split("\n")
        self.assertTrue(all(text_width(l) <= self.LIMIT for l in visible), text)
        self.assertEqual(lines, len(visible))
        self.assertIn("\\c[05]", text)                                  # codes survive

    def test_paragraph_break_and_line_ending_are_kept(self):
        text, _ = fit_db_text(TUTORIAL_EN, TUTORIAL_JA[0], self.LIMIT, 11)
        self.assertIn("\r\n\r\n", text)                                 # blank line between paragraphs
        self.assertNotIn("\n\n", text.replace("\r\n", ""))
        self.assertTrue(all("\n" not in part.replace("\r\n", "") for part in text.split("\r\n")))

    def test_words_are_not_lost_or_reordered(self):
        text, _ = fit_db_text(TUTORIAL_EN, TUTORIAL_JA[0], self.LIMIT, 11)
        self.assertEqual(" ".join(text.split()), " ".join(TUTORIAL_EN.split()))

    def test_wrapping_twice_changes_nothing(self):
        once, _ = fit_db_text(TUTORIAL_EN, TUTORIAL_JA[0], self.LIMIT, 11)
        twice, _ = fit_db_text(once, TUTORIAL_JA[0], self.LIMIT, 11)
        self.assertEqual(once, twice)

    def test_text_that_fits_is_returned_untouched(self):
        fits = "Short line.\n\nSecond paragraph."
        self.assertEqual(fit_db_text(fits, TUTORIAL_JA[0], self.LIMIT, 11), (fits, 3))
        crlf = "Short line.\r\nSecond."
        self.assertEqual(fit_db_text(crlf, TUTORIAL_JA[0], self.LIMIT, 11)[0], crlf)

    def test_tall_result_is_reflowed_per_paragraph(self):
        broken = "\n".join(["word word word"] * 12) + "\n\n" + "\n".join(["last words"] * 3)
        text, lines = fit_db_text(broken, "x\r\ny", 49, 6)
        plain_lines = len(broken.split("\n"))
        self.assertLess(lines, plain_lines)
        self.assertIn("\r\n\r\n", text)                                 # still two paragraphs


class StorePassTests(unittest.TestCase):
    def _store(self, translated):
        store = EditorStore(":memory:")
        entries = [(_path(i + 1), TUTORIAL_JA[i], "system") for i in range(3)]
        entries.append((_path(1, 1), "ロングソード", "system"))            # single-line field
        store.load_entries({FILE: entries})
        cur = store.conn.cursor()
        for i, text in enumerate(translated):
            cur.execute("UPDATE entries SET translated_text = ?, translation_source = 'auto' WHERE json_path = ?",
                        (text, _path(i + 1)))
        cur.execute("UPDATE entries SET translated_text = ?, translation_source = 'auto' WHERE json_path = ?",
                    ("A very long sword name that has no line break and must stay in one piece " * 2, _path(1, 1)))
        store.conn.commit()
        return store

    def _row(self, store, path):
        return store.conn.execute("SELECT * FROM entries WHERE json_path = ?", (path,)).fetchone()

    def test_load_wraps_the_reported_tutorial_and_marks_it_unsaved(self):
        store = self._store([TUTORIAL_EN, "Short.", "Short too."])
        result = store.apply_line_wrap(0)
        row = self._row(store, _path(1))
        self.assertEqual(result["db_wrapped"], 1)
        self.assertEqual(result["wrapped"], 1)
        self.assertEqual(row["is_modified"], 1)
        self.assertTrue(all(text_width(l) <= 49 for l in row["translated_text"].replace("\r\n", "\n").split("\n")))
        again = store.apply_line_wrap(0)                               # stable on every load and Save
        self.assertEqual(again["db_wrapped"], 0)

    def test_single_line_fields_are_not_touched(self):
        store = self._store([TUTORIAL_EN, "Short.", "Short too."])
        before = self._row(store, _path(1, 1))["translated_text"]
        store.apply_line_wrap(0)
        self.assertEqual(self._row(store, _path(1, 1))["translated_text"], before)

    def test_untranslated_rows_stay_japanese(self):
        store = self._store([TUTORIAL_JA[0], TUTORIAL_JA[1], TUTORIAL_JA[2]])
        self.assertEqual(store.apply_line_wrap(0)["db_wrapped"], 0)

    def test_text_taller_than_the_window_is_flagged(self):
        tall = "\n".join(["Some words on a line of their own here."] * 14)
        store = self._store([tall, "Short.", "Short too."])
        result = store.apply_line_wrap(0)
        row = self._row(store, _path(1))
        self.assertEqual(result["db_too_tall"], 1)
        self.assertIn("More lines than this window shows", row["warning_msg"])
        self.assertEqual(row["has_warning"], 1)

    def test_flag_is_removed_when_the_text_fits_again(self):
        store = self._store(["\n".join(["Some words on a line of their own here."] * 14), "S.", "S."])
        store.apply_line_wrap(0)
        store.conn.execute("UPDATE entries SET translated_text = 'Fits.' WHERE json_path = ?", (_path(1),))
        store.conn.commit()
        store.apply_line_wrap(0)
        self.assertEqual(self._row(store, _path(1))["has_warning"], 0)

    def test_it_can_be_switched_off(self):
        store = self._store([TUTORIAL_EN, "Short.", "Short too."])
        self.assertEqual(store.apply_line_wrap(0, db_text=False)["db_wrapped"], 0)
        self.assertEqual(self._row(store, _path(1))["translated_text"], TUTORIAL_EN)


class MessageTests(unittest.TestCase):
    def test_load_message_mentions_database_text(self):
        text = _wrap_message({"wrapped": 5, "db_wrapped": 5, "limit": 53})
        self.assertIn("5 database texts", text)
        self.assertNotIn("message window", text)
        both = _wrap_message({"wrapped": 7, "db_wrapped": 5, "limit": 53})
        self.assertIn("2 long translated lines", both)
        self.assertIn("5 database texts", both)
        self.assertEqual(_wrap_message({"wrapped": 0, "limit": 53}), "")


if __name__ == "__main__":
    unittest.main()
