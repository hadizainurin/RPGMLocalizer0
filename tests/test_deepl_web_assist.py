"""Browser hand-off to DeepL's public web translator (no API, no key)."""
import unittest
from unittest.mock import MagicMock
from urllib.parse import unquote

from src.backend.editor_backend import EditorBackend


class _Backend(EditorBackend):
    """EditorBackend with the Qt plumbing stubbed out."""

    def __init__(self, entry, settings=None):  # noqa: D107
        self._store = MagicMock()
        self._store.get_entry.return_value = entry
        self.settings_backend = MagicMock()
        self.settings_backend.get_dict.return_value = settings or {
            "source_lang": "ja", "target_lang": "en",
        }


class DeeplWebUrlTests(unittest.TestCase):
    def _url(self, original, **settings):
        be = _Backend({"id": 1, "original_text": original}, settings or None)
        return EditorBackend.deeplWebUrl(be, 1)

    def test_url_targets_the_public_translator(self) -> None:
        url = self._url("\u3053\u3093\u306b\u3061\u306f")
        self.assertTrue(url.startswith("https://www.deepl.com/translator#"))
        self.assertNotIn("api", url.split("#")[0])
        self.assertNotIn("jsonrpc", url)

    def test_language_pair_is_in_the_fragment(self) -> None:
        self.assertIn("#ja/en/", self._url("\u3042"))

    def test_auto_source_is_passed_as_auto(self) -> None:
        url = self._url("\u3042", source_lang="", target_lang="en")
        self.assertIn("#auto/en/", url)

    def test_text_is_encoded_so_slashes_cannot_split_the_fragment(self) -> None:
        url = self._url("a/b c&d")
        payload = url.split("/", 5)[-1]
        self.assertNotIn("/", payload)
        self.assertNotIn(" ", payload)
        self.assertEqual(unquote(payload), "a/b c&d")

    def test_empty_entry_yields_no_url(self) -> None:
        self.assertEqual(self._url("   "), "")

    def test_codes_are_stripped_before_sending(self) -> None:
        """Escape codes are restored on paste, so DeepL never sees them."""
        url = self._url("\\V[1]\u3042\u3042")
        self.assertNotIn("V%5B1%5D", url)


class NextEntryTests(unittest.TestCase):
    def test_returns_minus_one_when_nothing_is_left(self) -> None:
        be = _Backend({"id": 1, "original_text": "x"})
        be._selected_file, be._selected_category, be._search_query = "all", "all", ""
        be._store.get_untranslated_batch.return_value = []
        self.assertEqual(EditorBackend.nextUntranslatedAfter(be, 5), -1)

    def test_returns_the_next_id(self) -> None:
        be = _Backend({"id": 1, "original_text": "x"})
        be._selected_file, be._selected_category, be._search_query = "all", "all", ""
        be._store.get_untranslated_batch.return_value = [{"id": 42}]
        self.assertEqual(EditorBackend.nextUntranslatedAfter(be, 5), 42)


if __name__ == "__main__":
    unittest.main()
