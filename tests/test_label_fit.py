"""Short labels in a narrow window are fitted by a user setting, not guessed.

False Myth 2, 2026-10-15: the equipment card (CommonEvent 197) draws stat names
such as "魔法攻撃力 +6" in a window about 14 full-width characters wide. The
English ("Magic Attack Power", "Front-row attack power") ran past its edge, and
the message wrap (53 characters) never touched it. The window width is not in
the game data, so the setting ``editor_label_chars`` ("Short Label Width")
tells the editor how wide it is; wider labels get a smaller font, never below
the smallest size, and are never wrapped (a second line would land on the next
label).
"""
import unittest

from src.core.editor.editor_store import EditorStore
from src.core.line_wrap import fit_label, is_label, text_width

CODES = "\\c[05]\\cself[07] \\cself[21]\\c[00]"
FRONT_JA, FRONT_EN = f"前衛攻撃力 {CODES}", f"Front-row attack power {CODES}"
MAGIC_JA, MAGIC_EN = f"魔法攻撃力 {CODES}", f"Magic Attack Power {CODES}"
BURST_JA, BURST_EN = f"バースト力 {CODES}", f"Burst Power {CODES}"
LONG_JA = "ここは広いメッセージウィンドウで表示される、とても長い説明の文章です。続きもあります。"


class FitLabelTests(unittest.TestCase):
    def test_is_label(self):
        self.assertTrue(is_label(MAGIC_JA, 22))
        self.assertFalse(is_label(LONG_JA, 22))
        self.assertFalse(is_label("Already English", 22))

    def test_wider_label_gets_a_smaller_font(self):
        new, size, fits = fit_label(FRONT_EN, 22, 24, 18)
        self.assertTrue(fits)
        self.assertLess(size, 24)
        self.assertTrue(new.startswith(f"\\f[{size}]"))
        self.assertLessEqual(text_width(FRONT_EN) * size, 22 * 24)     # fits at that size
        self.assertGreater(text_width(FRONT_EN) * (size + 1), 22 * 24)  # the largest that does

    def test_label_that_fits_is_untouched(self):
        self.assertEqual(fit_label(BURST_EN, 22, 24, 18), (BURST_EN, 24, True))

    def test_nothing_fits_uses_the_smallest_size_and_says_so(self):
        new, size, fits = fit_label(FRONT_EN, 10, 24, 18)
        self.assertEqual((size, fits), (18, False))
        self.assertTrue(new.startswith("\\f[18]"))

    def test_lines_are_never_added(self):
        two = f"{MAGIC_EN}\n(Only during combat)"
        new, _, _ = fit_label(two, 20, 24, 18)
        self.assertEqual(new.count("\n"), 1)


class StoreTests(unittest.TestCase):
    def _store(self):
        store = EditorStore(":memory:")
        store.load_entries({"/g/CommonEvent.dat": [
            ("e/197/a", FRONT_JA, "string_op"), ("e/197/b", MAGIC_JA, "string_op"),
            ("e/197/c", BURST_JA, "string_op"), ("e/9/long", LONG_JA, "string_op"),
            ("e/9/say", "こんにちは", "dialogue"),
        ]})
        english = {"e/197/a": FRONT_EN, "e/197/b": MAGIC_EN, "e/197/c": BURST_EN,
                   "e/9/long": "This is a very long explanation shown in the wide message window. More follows.",
                   "e/9/say": "Hello there, it is really nice to see you again after such a long time!"}
        cur = store.conn.cursor()
        for jp, text in english.items():
            cur.execute("UPDATE entries SET translated_text = ?, translation_source = 'auto', "
                        "is_modified = 0 WHERE json_path = ?", (text, jp))
        store.conn.commit()
        return store

    def _rows(self, store):
        cur = store.conn.cursor()
        cur.execute("SELECT json_path, translated_text, is_modified, warning_msg FROM entries")
        return {r["json_path"]: (r["translated_text"], r["is_modified"], r["warning_msg"]) for r in cur.fetchall()}

    def _run(self, store, label_chars, min_font=18):
        return store.apply_line_wrap(0, shrink_font=True, min_font=min_font, default_font=24,
                                     label_chars=label_chars)

    def test_off_by_default(self):
        store = self._store()
        before = self._rows(store)
        result = store.apply_line_wrap(0, shrink_font=True, default_font=24)
        self.assertEqual(result["label_shrunk"], 0)
        self.assertEqual(self._rows(store)["e/197/a"][0], before["e/197/a"][0])

    def test_labels_are_fitted_and_nothing_else(self):
        store = self._store()
        result = self._run(store, 22)
        rows = self._rows(store)
        self.assertEqual(result["label_shrunk"], 2)                     # Front-row and Magic; Burst fits
        self.assertTrue(rows["e/197/a"][0].startswith("\\f["))
        self.assertEqual(rows["e/197/a"][1], 1)                         # unsaved: Save writes it
        self.assertEqual(rows["e/197/c"][0], BURST_EN)
        self.assertNotIn("\\f[", rows["e/9/long"][0])                   # not a label
        self.assertNotIn("\\f[", rows["e/9/say"][0])                    # not string_op

    def test_stable_on_every_load_and_save(self):
        store = self._store()
        self._run(store, 22)
        after = self._rows(store)
        again = self._run(store, 22)
        self.assertEqual(again["label_shrunk"], 2)                      # recomputed from the normal size
        self.assertEqual(self._rows(store), after)

    def test_turning_it_off_restores_the_normal_size(self):
        store = self._store()
        self._run(store, 22)
        self._run(store, 0)
        self.assertEqual(self._rows(store)["e/197/a"][0], FRONT_EN)

    def test_a_label_that_cannot_fit_gets_a_warning_that_clears(self):
        store = self._store()
        result = self._run(store, 17)        # only labels no wider than 17 in Japanese count
        self.assertEqual(result["label_too_wide"], 2)                   # Front-row and Magic
        self.assertIn("Wider than the label window", self._rows(store)["e/197/a"][2])
        self.assertEqual(self._rows(store)["e/197/c"][2], "")            # Burst fits
        self._run(store, 40)
        self.assertEqual(self._rows(store)["e/197/a"][2], "")


if __name__ == "__main__":
    unittest.main()
