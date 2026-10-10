"""Control-code-only lines must never reach a translation engine.

A WOLF line like \\E\\c[00]\\f[24]\\A+\\s[000]\\c[00]\\f[25]\\N contains no
language. Sent to a model it came back as "\\c[00]\\f[24] \\E\\|\\A+ s[000]..."
- codes reordered, a backslash dropped, \\| invented - which rendered in-game as
"[2] \\font\\| s[000] [0]".
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication

from src.backend.editor_backend import AutoTranslateWorker
from src.core.editor.editor_store import EditorStore
from src.core.text_segmenter import clean_text, has_translatable_content
from src.core.syntax_guard_rpgm import protect_rpgm_syntax

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

#: Taken verbatim from the corrupted rows in the user's CommonEvent.dat.
CODE_ONLY = [
    r"\E\c[00]\f[24]\A+\s[000]\c[00]\f[25]\N",
    r"\A+\font[0]\c[19]\f[26]\s[000]\c[00]\f[25]",
    r"\E\A+\font[0]\c[00]\f[26]\s[000]\c[00]\f[25]\N",
    r"\E\font[2]\c[00]\f[24]\A+\s[000]\c[00]\f[25]\font[0]\N",
]

REAL_DIALOGUE = [
    r"\c[1]男の子「パパ…ごめんなさい」\N",
    r"\E\A+勇者は\s[000]を手にした\N",
    "ただのテキスト",
]


class MaskingTests(unittest.TestCase):
    def test_every_code_is_masked(self) -> None:
        for src in CODE_ONLY:
            with self.subTest(src=src):
                clean, _ = clean_text(src)
                residue = clean.replace("|||TXTSEG|||", "").strip()
                self.assertEqual(residue, "", f"leaked {residue!r}")

    def test_individual_wolf_codes(self) -> None:
        for code in (r"\E", r"\A", r"\A+", r"\N", r"\s[000]", r"\font[0]",
                     r"\c[00]", r"\f[24]", r"\cself[30]"):
            with self.subTest(code=code):
                clean, _ = clean_text(code)
                self.assertEqual(clean.replace("|||TXTSEG|||", "").strip(), "")

    def test_syntax_guard_agrees_with_the_segmenter(self) -> None:
        """Both regexes are maintained in parallel and must not drift."""
        for src in CODE_ONLY:
            with self.subTest(src=src):
                protected, placeholders = protect_rpgm_syntax(src)
                import re
                self.assertEqual(re.sub(r"⟦[^⟧]+⟧", "", protected).strip(), "")
                self.assertTrue(placeholders)

    def test_dialogue_still_survives_masking(self) -> None:
        for src in REAL_DIALOGUE:
            with self.subTest(src=src):
                clean, _ = clean_text(src)
                self.assertTrue(clean.strip())


class TranslatableContentTests(unittest.TestCase):
    def test_code_only_is_not_translatable(self) -> None:
        for src in CODE_ONLY:
            with self.subTest(src=src):
                self.assertFalse(has_translatable_content(src))

    def test_dialogue_is_translatable(self) -> None:
        for src in REAL_DIALOGUE:
            with self.subTest(src=src):
                self.assertTrue(has_translatable_content(src))

    def test_unknown_future_codes_are_still_refused(self) -> None:
        """The backstop, for codes no regex here knows about yet."""
        self.assertFalse(has_translatable_content(r"\QQQ[9]\ZZZ+\WHATEVER[0]"))

    def test_numbers_and_punctuation_alone_are_not_language(self) -> None:
        for src in ("12345", "...", "---", r"\n\n", "   "):
            with self.subTest(src=src):
                self.assertFalse(has_translatable_content(src))

    def test_short_latin_is_language(self) -> None:
        self.assertTrue(has_translatable_content("OK go"))


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EditorStore(":memory:")
        texts = CODE_ONLY + ["ああ"]
        self.store.load_entries({"CommonEvent.dat": [
            (f"p{i}", t, "dialogue") for i, t in enumerate(texts)]})

    def tearDown(self) -> None:
        self.store.close()

    def _run(self):
        w = AutoTranslateWorker(
            self.store,
            {"engine": "pseudo", "source_lang": "ja", "target_lang": "en",
             "use_cache": False},
            file_filter="all", category_filter="all")
        seen = []
        w.finished.connect(lambda n, m: seen.append((n, m)))
        w.run()
        return seen[-1]

    def test_code_only_rows_are_left_untouched(self) -> None:
        self._run()
        rows = {r["original_text"]: r for r in self.store.query_page(page_size=20)[0]}
        for src in CODE_ONLY:
            with self.subTest(src=src):
                self.assertEqual(rows[src]["translated_text"], src)
                self.assertEqual(rows[src]["translation_source"], "")

    def test_the_real_line_is_still_translated(self) -> None:
        self._run()
        rows = {r["original_text"]: r for r in self.store.query_page(page_size=20)[0]}
        self.assertNotEqual(rows["ああ"]["translated_text"], "ああ")

    def test_code_only_skips_are_reported(self) -> None:
        _n, msg = self._run()
        self.assertIn("control codes only", msg)


if __name__ == "__main__":
    unittest.main()


class RealProjectCodeTests(unittest.TestCase):
    """Code shapes taken from a real WOLF title's CommonEvent.dat.

    The enumerated code-name list could never keep up - this one game uses
    \\wE \\cE \\v1 \\font, none of which were listed - so the pattern matches the
    SHAPE "backslash, short name, bracket group" instead.
    """

    #: (source line, the dialogue that must survive). Raw strings hold the
    #: backslash codes; the Japanese is a separate literal so \u escapes resolve.
    LEAKY_IN_THE_WILD = [
        (r"\-[06]\wE[03]\cE[19]\font[3]" + "\u2605\u614b\u52e2\u3092\u7acb\u3066\u76f4\u305d\u3046\uff01",
         "\u2605\u614b\u52e2\u3092\u7acb\u3066\u76f4\u305d\u3046\uff01"),
        ("Round\u3000" + r"\v1 [026] [025]", "Round"),
        (r"\c[05]" + "\u30c0\u30e1\u30fc\u30b8\u30ab\u30c3\u30c8\u7387" + r"\v1[035]%\c[00]",
         "\u30c0\u30e1\u30fc\u30b8\u30ab\u30c3\u30c8\u7387"),
    ]

    def test_no_backslash_code_reaches_the_model(self) -> None:
        import re
        for src, _expected in self.LEAKY_IN_THE_WILD:
            with self.subTest(src=src):
                clean, _ = clean_text(src)
                self.assertEqual(
                    re.findall(r"\\[A-Za-z\[\]+\-]+", clean), [],
                    f"code leaked from {src!r} as {clean!r}")

    def test_the_dialogue_itself_survives(self) -> None:
        for src, expected in self.LEAKY_IN_THE_WILD:
            with self.subTest(src=src):
                clean, _ = clean_text(src)
                self.assertIn(expected, clean.replace("|||TXTSEG|||", ""))

    def test_unlisted_code_names_are_handled_by_shape(self) -> None:
        """A name nobody has seen yet must still be masked."""
        for code in (r"\zzz[1]", r"\q9[42]", r"\newcode [7]", r"\ABCDEFGH[0]"):
            with self.subTest(code=code):
                clean, _ = clean_text(code)
                self.assertEqual(clean.replace("|||TXTSEG|||", "").strip(), "")

    def test_prose_with_a_bracket_is_not_eaten(self) -> None:
        clean, _ = clean_text("\u5f7c\u306f\u8a00\u3063\u305f\u300c\u3084\u3042\u300d")
        self.assertIn("\u5f7c\u306f\u8a00\u3063\u305f", clean)


if __name__ == "__main__":
    unittest.main()
