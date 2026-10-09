"""Tests for the user-authored Local LLM prompt and tolerant response parsing."""
import unittest

from src.core.translators.services import LocalLLMTranslator, OpenAICompatibleTranslator


# A prompt in the shape users actually write: literal braces in the output spec
# (which breaks str.format) plus {source}/{target} template tokens.
USER_PROMPT = (
    "You are a professional {source}-to-{target} translator.\n"
    "Reply with ONE JSON object exactly: {\"t\": [\"line 1\", \"line 2\"]}.\n"
    "Codes: {source_code} -> {target_code}"
)


def _make(**kwargs) -> LocalLLMTranslator:
    kwargs.setdefault("model", "qwen2.5")
    return LocalLLMTranslator(base_url="http://127.0.0.1:8080/v1", api_key="", **kwargs)


class ParseTranslationsTests(unittest.TestCase):
    def test_bare_array(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._parse_translations('["a", "b"]'), ["a", "b"]
        )

    def test_translations_key(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._parse_translations('{"translations": ["a"]}'), ["a"]
        )

    def test_short_t_key(self) -> None:
        """A custom prompt may specify {"t": [...]}; it must not be discarded."""
        self.assertEqual(
            OpenAICompatibleTranslator._parse_translations('{"t": ["a", "b"]}'), ["a", "b"]
        )

    def test_fenced_t_key(self) -> None:
        payload = '```json\n{"t": ["あ", "b"]}\n```'
        self.assertEqual(OpenAICompatibleTranslator._parse_translations(payload), ["あ", "b"])

    def test_unknown_dict_rejected(self) -> None:
        self.assertIsNone(OpenAICompatibleTranslator._parse_translations('{"nope": 1}'))


class PromptModeTests(unittest.TestCase):
    def test_default_is_builtin_prompt(self) -> None:
        tr = _make()
        prompt = tr._build_system_prompt("English", "ja")
        self.assertIn("expert game localizer", prompt)

    def test_append_keeps_output_contract(self) -> None:
        tr = _make(system_prompt=USER_PROMPT, prompt_mode="append")
        prompt = tr._build_system_prompt("English", "ja")
        self.assertIn("professional Japanese-to-English translator", prompt)
        self.assertIn("expert game localizer", prompt)

    def test_override_drops_builtin(self) -> None:
        tr = _make(system_prompt=USER_PROMPT, prompt_mode="override")
        prompt = tr._build_system_prompt("English", "ja")
        self.assertIn("professional Japanese-to-English translator", prompt)
        self.assertNotIn("expert game localizer", prompt)

    def test_literal_braces_survive_substitution(self) -> None:
        """str.format() would raise KeyError on the {"t": [...]} spec."""
        tr = _make(system_prompt=USER_PROMPT, prompt_mode="override")
        prompt = tr._build_system_prompt("English", "ja")
        self.assertIn('{"t": ["line 1", "line 2"]}', prompt)

    def test_language_code_tokens(self) -> None:
        tr = _make(system_prompt=USER_PROMPT, prompt_mode="override")
        self.assertIn("ja -> en", tr._build_system_prompt("en", "ja"))

    def test_auto_source_has_readable_name(self) -> None:
        tr = _make(system_prompt="From {source} to {target}.", prompt_mode="override")
        self.assertEqual(
            tr._build_system_prompt("en", "auto"), "From the source language to English."
        )

    def test_invalid_mode_falls_back_to_append(self) -> None:
        tr = _make(system_prompt="x", prompt_mode="nonsense")
        self.assertEqual(tr.prompt_mode, "append")

    def test_blank_prompt_ignored(self) -> None:
        tr = _make(system_prompt="   ", prompt_mode="override")
        self.assertIn("expert game localizer", tr._build_system_prompt("English", "ja"))

    def test_dump_disabled_by_default(self) -> None:
        self.assertFalse(_make().debug_dump)


if __name__ == "__main__":
    unittest.main()


class BlankModelTests(unittest.TestCase):
    """llama.cpp users supply only an address; a blank model must not become 'llama3'."""

    def test_blank_model_is_not_coerced_by_factory(self) -> None:
        from src.core.translators.manager import create_translator
        tr = create_translator({
            "engine": "local_llm",
            "local_llm_url": "http://192.168.1.50:8080/v1",
            "local_llm_model": "",
        })
        self.assertIsInstance(tr, LocalLLMTranslator)
        self.assertEqual(tr.model, "")
        self.assertFalse(tr._model_probed)

    def test_named_model_is_kept_and_not_probed(self) -> None:
        tr = _make(model="qwen2.5")
        self.assertEqual(tr.model, "qwen2.5")
        self.assertTrue(tr._model_probed)

    def test_endpoint_built_from_base_url(self) -> None:
        tr = LocalLLMTranslator(model="", base_url="http://192.168.1.50:8080/v1", api_key="")
        self.assertEqual(tr.endpoint, "http://192.168.1.50:8080/v1/chat/completions")

    def test_probe_falls_back_when_server_unreachable(self) -> None:
        import asyncio
        tr = LocalLLMTranslator(model="", base_url="http://127.0.0.1:9/v1", api_key="")
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(tr._ensure_model())
        self.assertEqual(tr.model, LocalLLMTranslator.FALLBACK_MODEL)

    def test_hy_mt2_does_not_probe(self) -> None:
        from src.core.translators.services import HyMT2Translator
        self.assertFalse(HyMT2Translator.PROBE_MODEL_IF_BLANK)


class DefaultsTests(unittest.TestCase):
    """A fresh install should point at llama.cpp with no model name."""

    def test_translator_class_defaults(self) -> None:
        tr = LocalLLMTranslator()
        self.assertEqual(tr.base_url, "http://localhost:8080/v1")
        self.assertEqual(tr.model, "")

    def test_factory_defaults_with_no_settings(self) -> None:
        from src.core.translators.manager import create_translator
        tr = create_translator({"engine": "local_llm"})
        self.assertEqual(tr.base_url, "http://localhost:8080/v1")
        self.assertEqual(tr.model, "")

    def test_constants_default(self) -> None:
        from src.core.constants import AI_LOCAL_URL
        self.assertEqual(AI_LOCAL_URL, "http://localhost:8080/v1")

    def test_settings_defaults(self) -> None:
        from src.backend.settings_backend import SettingsBackend
        defaults = SettingsBackend.__init__.__doc__  # placeholder guard
        del defaults
        import re, io as _io
        src = _io.open("src/backend/settings_backend.py", encoding="utf-8").read()
        self.assertIn('"local_llm_url": "http://localhost:8080/v1"', src)
        self.assertIn('"local_llm_model": ""', src)
