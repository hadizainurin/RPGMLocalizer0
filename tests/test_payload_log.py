"""Payload dumps rotate: request_1..5 / response_1..5, 50 MB each, 500 MB max."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils import payload_log  # noqa: E402


class PayloadLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        payload_log.write._folded = False

    def tearDown(self):
        self.tmp.cleanup()

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_records_append_to_one_file_per_kind(self):
        payload_log.write(self.dir, "request", {"a": 1}, "x1")
        payload_log.write(self.dir, "response", '{"t": ["A"]}', "x1")
        payload_log.write(self.dir, "request", {"a": 2}, "x2")
        self.assertEqual(self.names(), ["request_1.jsonl", "response_1.jsonl"])
        lines = (self.dir / "request_1.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l)["id"] for l in lines], ["x1", "x2"])

    def test_rotates_and_drops_the_oldest(self):
        with mock.patch.object(payload_log, "MAX_FILE_BYTES", 10):
            for i in range(7):
                payload_log.write(self.dir, "request", {"n": i}, f"id{i}")
        self.assertEqual(self.names(), [f"request_{n}.jsonl" for n in range(1, 6)])
        first = json.loads((self.dir / "request_1.jsonl").read_text(encoding="utf-8"))
        last = json.loads((self.dir / "request_5.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((first["id"], last["id"]), ("id2", "id6"))

    def test_old_one_file_per_call_dumps_are_folded_in(self):
        (self.dir / "20261011-014143-206d977f4d0-request.json").write_text('{"model": "m"}', encoding="utf-8")
        (self.dir / "20261011-014220-206d977f4d0-response.json").write_text('{"raw": "x"}', encoding="utf-8")
        payload_log.write(self.dir, "request", {"new": True}, "n1")
        self.assertEqual(self.names(), ["request_1.jsonl", "response_1.jsonl"])
        self.assertEqual(len((self.dir / "request_1.jsonl").read_text(encoding="utf-8").splitlines()), 2)

    def test_cap(self):
        self.assertEqual(2 * payload_log.MAX_FILES * payload_log.MAX_FILE_BYTES, 500 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
