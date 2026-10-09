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
    return LocalLLMTranslator(
        model="qwen2.5", base_url="http://127.0.0.1:8080/v1", api_key="", **kwargs
    )


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
