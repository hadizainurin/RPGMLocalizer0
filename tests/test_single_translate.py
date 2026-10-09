"""The editor's right-click 'Translate with' path."""
import unittest

from src.backend.editor_backend import SINGLE_TRANSLATE_ENGINES, SingleTranslateWorker
from src.core.translators.manager import create_translator
from src.core.translators.services import (
    DeepLTranslator, LibreTranslateTranslator, LocalLLMTranslator,
)
from src.core.translators.google import GoogleTranslator


class EngineListTests(unittest.TestCase):
    def test_every_listed_engine_is_constructible(self) -> None:
        """A menu entry that create_translator cannot build would fail at click time."""
        for spec in SINGLE_TRANSLATE_ENGINES:
            if not spec["id"]:
                continue  # "Current engine" passes no override
            with self.subTest(engine=spec["id"]):
                tr = create_translator({"engine": spec["id"], "deepl_api_key": "x:fx"})
                self.assertIsNotNone(tr)

    def test_free_options_need_no_credentials(self) -> None:
        by_id = {s["id"]: s for s in SINGLE_TRANSLATE_ENGINES}
        self.assertEqual(by_id["google"]["needs_key"], "")
        self.assertEqual(by_id["local_llm"]["needs_key"], "")
        self.assertEqual(by_id["libretranslate"]["needs_key"], "")

    def test_google_is_offered_and_is_the_free_web_client(self) -> None:
        self.assertIn("google", {s["id"] for s in SINGLE_TRANSLATE_ENGINES})
        self.assertIsInstance(create_translator({"engine": "google"}), GoogleTranslator)

    def test_local_llm_entry_builds_local_translator(self) -> None:
        self.assertIsInstance(
            create_translator({"engine": "local_llm"}), LocalLLMTranslator
        )

    def test_libretranslate_entry_builds(self) -> None:
        self.assertIsInstance(
            create_translator({"engine": "libretranslate"}), LibreTranslateTranslator
        )

    def test_ids_are_unique(self) -> None:
        ids = [s["id"] for s in SINGLE_TRANSLATE_ENGINES]
        self.assertEqual(len(ids), len(set(ids)))


class DeepLFreeTests(unittest.TestCase):
    """One DeepL entry covers both tiers; the key suffix picks the endpoint."""

    def test_free_key_selects_free_endpoint(self) -> None:
        tr = DeepLTranslator(api_key="abc123:fx")
        self.assertEqual(tr._resolve_base_url(), DeepLTranslator.base_url_free)

    def test_pro_key_selects_paid_endpoint(self) -> None:
        tr = DeepLTranslator(api_key="abc123")
        self.assertEqual(tr._resolve_base_url(), DeepLTranslator.base_url_paid)


class WorkerTests(unittest.TestCase):
    def test_engine_override_does_not_mutate_caller_settings(self) -> None:
        settings = {"engine": "google", "target_lang": "en"}
        worker = SingleTranslateWorker(None, settings, 1, "deepl")
        self.assertEqual(settings["engine"], "google")
        self.assertEqual(worker.settings["engine"], "deepl")
        self.assertEqual(worker.engine, "deepl")

    def test_blank_engine_keeps_the_configured_one(self) -> None:
        worker = SingleTranslateWorker(None, {"engine": "gemini"}, 1, "")
        self.assertEqual(worker.settings["engine"], "gemini")
        self.assertEqual(worker.engine, "gemini")


if __name__ == "__main__":
    unittest.main()
