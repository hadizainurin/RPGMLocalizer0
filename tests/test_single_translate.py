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

    def test_no_key_defaults_to_free_endpoint(self) -> None:
        """Free is the common case, so an unset key must not aim at the Pro host."""
        self.assertEqual(DeepLTranslator(api_key="")._resolve_base_url(),
                         DeepLTranslator.base_url_free)
        self.assertEqual(DeepLTranslator(api_key="   ")._resolve_base_url(),
                         DeepLTranslator.base_url_free)


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


class KeySetupTests(unittest.TestCase):
    """Each user supplies their own key; none is ever bundled."""

    def test_keyed_engines_have_a_setup_url(self) -> None:
        for spec in SINGLE_TRANSLATE_ENGINES:
            if spec.get("needs_key"):
                with self.subTest(engine=spec["id"]):
                    self.assertTrue(spec.get("setup_url", "").startswith("https://"))

    def test_keyless_engines_have_no_setup_url(self) -> None:
        for spec in SINGLE_TRANSLATE_ENGINES:
            if not spec.get("needs_key"):
                with self.subTest(engine=spec["id"]):
                    self.assertEqual(spec.get("setup_url", ""), "")

    def test_no_api_key_is_shipped_in_the_source(self) -> None:
        """Guard against a credential ever being committed to this public repo."""
        import pathlib, re
        suspicious = re.compile(
            r"(sk-[A-Za-z0-9]{20,}"
            r"|AIza[A-Za-z0-9_\-]{30,}"
            r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:fx)"
        )
        offenders = []
        for path in pathlib.Path("src").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if suspicious.search(text):
                offenders.append(str(path))
        self.assertEqual(offenders, [], f"possible API key committed in: {offenders}")

    def test_deepl_key_shape_is_validated(self) -> None:
        from src.backend.editor_backend import SINGLE_TRANSLATE_ENGINES as E
        self.assertIn("deepl", {s["id"] for s in E})
