"""Local LLM requests constrain the reply with a JSON schema.

Payload logs: ~40% of replies were rejected (mis-escaped quotes, wrong item
count), each costing 2-3 more requests; some replies were romaji.
"""
import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.translators.services import LocalLLMTranslator, OpenAICompatibleTranslator  # noqa: E402
from src.core.translation_quality import looks_romanized, safe_to_reuse, translation_issues  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, replies):
        self.replies, self.payloads = list(replies), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.payloads.append(json)
        return _Resp(*self.replies.pop(0))


def _ok(items):
    return (200, {"choices": [{"message": {"content": json.dumps({"t": items})}}]})


class StructuredOutputTests(unittest.TestCase):
    def _translator(self, replies):
        t = LocalLLMTranslator(model="m", base_url="http://localhost:8080/v1")
        session = _Session(replies)

        async def get_session():
            return session
        t._get_session = get_session
        return t, session

    def test_schema_pins_item_count_and_temperature_is_zero(self):
        t, session = self._translator([_ok(["a", "b", "c"])])
        out = asyncio.run(t._translate_clean_texts(["あ", "い", "う"], "ja", "en"))
        self.assertEqual(out, ["a", "b", "c"])
        p = session.payloads[0]
        arr = p["response_format"]["json_schema"]["schema"]["properties"]["t"]
        self.assertEqual((arr["minItems"], arr["maxItems"]), (3, 3))
        self.assertEqual(p["temperature"], 0.0)

    def test_server_without_schema_support_falls_back(self):
        t, session = self._translator([(400, {"error": "unsupported"}), _ok(["a"])])
        t.max_retries = 3
        out = asyncio.run(t._translate_clean_texts(["あ"], "ja", "en"))
        self.assertEqual(out, ["a"])
        self.assertNotIn("response_format", session.payloads[-1])
        self.assertTrue(t._structured_output_unsupported)

    def test_hosted_apis_send_no_schema(self):
        self.assertEqual(OpenAICompatibleTranslator._payload_extras(object(), 3), {})

    def test_default_prompt_matches_the_object_format(self):
        t = LocalLLMTranslator(model="m")
        prompt = t._build_system_prompt("en", "ja")
        self.assertIn('{"t": [...]}', prompt)
        self.assertNotIn("JSON array with", prompt)


class RomajiTests(unittest.TestCase):
    ORIG = "「…ほ、本気か？\n　絶対…苦労することになると思うぞ…。」"

    def test_romaji_is_caught(self):
        romaji = "\"…H-honki ka?\n　Zettai…kurou suru koto ni naru to omou zo….\""
        self.assertTrue(looks_romanized(self.ORIG, romaji))
        self.assertFalse(safe_to_reuse(self.ORIG, romaji, "en"))
        self.assertIn("written in romaji, not translated", translation_issues(self.ORIG, romaji))

    def test_english_is_not(self):
        for english in ("\"…H-Honestly?\n　You'll definitely… have a hard time….\"",
                        "Don't make fun of me… I'm a man, you know.",
                        "Kyaa! It's a Rabibow, so cute!"):
            self.assertFalse(looks_romanized(self.ORIG, english), english)


if __name__ == "__main__":
    unittest.main()


class RunawayGuardTests(unittest.TestCase):
    def _translator(self, replies):
        t = LocalLLMTranslator(model="m", base_url="http://localhost:8080/v1")
        session = _Session(replies)

        async def get_session():
            return session
        t._get_session = get_session
        return t, session

    def test_local_requests_carry_a_generous_cap(self):
        t, session = self._translator([_ok(["a", "b"])])
        asyncio.run(t._translate_clean_texts(["あいうえお", "かきくけこ"], "ja", "en"))
        cap = session.payloads[0]["max_tokens"]
        self.assertGreaterEqual(cap, 512)

    def test_explicit_cap_wins(self):
        t, session = self._translator([_ok(["a"])])
        t.max_tokens_override = 2000
        asyncio.run(t._translate_clean_texts(["あ"], "ja", "en"))
        self.assertEqual(session.payloads[0]["max_tokens"], 2000)

    def test_hitting_the_cap_splits_instead_of_resending(self):
        looped = (200, {"choices": [{"message": {"content": '{"t": ["aaaa'}, "finish_reason": "length"}]})
        t, session = self._translator([looped, _ok(["A"]), _ok(["B"])])
        out = asyncio.run(t._translate_with_retry_and_fallback(["あ", "い"], "ja", "en"))
        self.assertEqual(out, ["A", "B"])
        self.assertEqual([len(json.loads(p["messages"][1]["content"])) for p in session.payloads], [2, 1, 1])

    def test_a_timeout_is_not_split(self):
        t, session = self._translator([])
        async def nothing(*a, **k):
            return [None, None]
        t._translate_clean_texts = nothing
        self.assertIsNone(asyncio.run(t._translate_with_retry_and_fallback(["あ", "い"], "ja", "en")))
