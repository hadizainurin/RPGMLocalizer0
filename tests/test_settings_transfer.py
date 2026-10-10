"""Settings export/import and the diagnostics report."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils import diagnostics, settings_transfer as st  # noqa: E402

CURRENT = {"engine": "local_llm", "batch_size": 12, "use_cache": True,
           "local_llm_url": "http://localhost:8080/v1", "openai_api_key": "sk-mine",
           "regex_blacklist": "", "local_llm_parallel": 1}


class SettingsTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "s.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_carries_version_and_no_keys(self):
        st.export_to(self.path, CURRENT, "1.1.3.12")
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((doc["format"], doc["app_version"]), ("rpgmlocalizer-settings", "1.1.3.12"))
        self.assertEqual(doc["settings_schema"], st.SETTINGS_SCHEMA)
        self.assertNotIn("openai_api_key", doc["settings"])

    def test_round_trip_keeps_local_keys(self):
        exported = dict(CURRENT, batch_size=20, openai_api_key="sk-theirs")
        st.export_to(self.path, exported, "1.1.3.12")
        merged, applied, skipped, version = st.import_from(self.path, CURRENT)
        self.assertEqual(merged["batch_size"], 20)
        self.assertEqual(merged["openai_api_key"], "sk-mine")
        self.assertEqual(skipped, [])

    def test_unknown_and_mistyped_keys_are_skipped(self):
        doc = st.build_export(dict(CURRENT, future_option=True, batch_size="lots"), "9.0.0")
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        merged, applied, skipped, _ = st.import_from(self.path, CURRENT)
        self.assertIn("future_option", skipped)
        self.assertIn("batch_size", skipped)
        self.assertEqual(merged["batch_size"], 12)

    def test_refusals(self):
        self.path.write_text('{"hello": 1}', encoding="utf-8")
        with self.assertRaises(st.ImportRefused):
            st.import_from(self.path, CURRENT)
        st.export_to(self.path, CURRENT, "1.1.2.5")
        with mock.patch.object(st, "INCOMPATIBLE_APP_VERSIONS", [("1.1.2.0", "1.1.2.9")]):
            with self.assertRaises(st.ImportRefused):
                st.import_from(self.path, CURRENT)
        with mock.patch.object(st, "MIN_IMPORT_SCHEMA", 2), mock.patch.object(st, "SETTINGS_SCHEMA", 2):
            with self.assertRaises(st.ImportRefused):
                st.import_from(self.path, CURRENT)

    def test_migration_upgrades_old_schema(self):
        st.export_to(self.path, dict(CURRENT, batch_size=7), "1.1.3.0")
        with mock.patch.object(st, "SETTINGS_SCHEMA", 2), \
             mock.patch.object(st, "MIGRATIONS", {1: lambda s: dict(s, batch_size=s["batch_size"] * 2)}):
            merged, *_ = st.import_from(self.path, CURRENT)
        self.assertEqual(merged["batch_size"], 14)

    def test_backend_slot_applies_and_reports(self):
        from src.backend.settings_backend import SettingsBackend
        backend = SettingsBackend.__new__(SettingsBackend)
        from PyQt6.QtCore import QObject
        QObject.__init__(backend)
        backend._data = dict(CURRENT)
        backend.save = lambda: None
        st.export_to(self.path, dict(CURRENT, batch_size=30), "1.1.3.12")
        res = backend.importSettingsFrom(str(self.path))
        self.assertTrue(res["ok"])
        self.assertEqual(backend._data["batch_size"], 30)
        self.assertIn("API keys were left unchanged", res["message"])


class SystemLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_content_and_redaction(self):
        server = {"data": [{"id": "C:\\TheRock\\Model\\shisa-v2-mistral-nemo-12b.Q8_0.gguf"}]}
        with mock.patch.object(diagnostics, "_get_json", side_effect=lambda url, timeout=3.0:
                               server if url.endswith("/models") else {"total_slots": 2}):
            path = diagnostics.write_report("translation_started", CURRENT, probe_server=True, folder=self.dir)
        self.assertEqual(path.name, "system.log")
        text = path.read_text(encoding="utf-8")
        self.assertIn("event   = translation_started", text)
        self.assertIn("engine  = local_llm", text)
        self.assertIn("model   = shisa-v2-mistral-nemo-12b.Q8_0.gguf", text)
        self.assertIn("openai_api_key = <set>", text)
        self.assertNotIn("sk-mine", text)
        self.assertIn("version = ", text)

    def test_model_is_empty_without_a_local_engine(self):
        path = diagnostics.write_report("translation_started", dict(CURRENT, engine="google"), folder=self.dir)
        text = path.read_text(encoding="utf-8")
        self.assertIn("model   = \n", text)
        # Fixed per release, so not repeated here.
        for noise in ("python", "pyqt", "qt =", "frozen"):
            self.assertNotIn(noise, text.lower().replace("python3", ""))

    def test_at_most_five_files_latest_first(self):
        for i in range(8):
            diagnostics.write_report(f"event{i}", CURRENT, folder=self.dir)
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(names, ["system.log", "system_1.log", "system_2.log",
                                 "system_3.log", "system_4.log"])
        self.assertIn("event7", (self.dir / "system.log").read_text())
        self.assertIn("event3", (self.dir / "system_4.log").read_text())

    def test_server_probe_failure_is_recorded_not_raised(self):
        with mock.patch.object(diagnostics, "_get_json", return_value={"error": "URLError: refused"}):
            path = diagnostics.write_report("app_started", CURRENT, probe_server=True, folder=self.dir)
        self.assertIn("refused", path.read_text())


class CrashLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_python_crash_is_written_with_state(self):
        diagnostics.write_report("translation_started", CURRENT, folder=self.dir)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import traceback
            path = diagnostics.write_crash_log("Unhandled exception:\n" + traceback.format_exc(), self.dir)
        self.assertTrue(path.name.startswith("crash_") and path.name.endswith(".log"))
        text = path.read_text(encoding="utf-8")
        self.assertIn("RuntimeError: boom", text)
        self.assertIn("engine = local_llm", text)

    def test_native_crash_left_by_faulthandler_is_collected(self):
        (self.dir / diagnostics.FAULT_FILE).write_text(
            "Fatal Python error: Segmentation fault\n  File main.py, line 1", encoding="utf-8")
        path = diagnostics.collect_native_crash(self.dir)
        self.assertIn("Segmentation fault", path.read_text(encoding="utf-8"))
        self.assertEqual((self.dir / diagnostics.FAULT_FILE).read_text(), "")
        self.assertIsNone(diagnostics.collect_native_crash(self.dir))   # not twice

    def test_only_the_newest_crash_logs_are_kept(self):
        with mock.patch.object(diagnostics, "MAX_CRASH_LOGS", 3):
            for i in range(5):
                diagnostics.write_crash_log(f"crash {i}", self.dir, when=1_700_000_000 + i)
        self.assertEqual(len(list(self.dir.glob("crash_*.log"))), 3)

    def test_unhandled_exception_hook_writes_a_crash_log(self):
        import sys as _sys, threading as _threading
        old_hook, old_thread_hook = _sys.excepthook, _threading.excepthook
        try:
            diagnostics.install_crash_handlers(self.dir)
            with mock.patch.object(_sys, "__excepthook__"):
                _sys.excepthook(ValueError, ValueError("bad"), None)
        finally:
            diagnostics.close_crash_handlers()
            _sys.excepthook, _threading.excepthook = old_hook, old_thread_hook
        crashes = list(self.dir.glob("crash_*.log"))
        self.assertEqual(len(crashes), 1)
        # Clean exit removes the empty faulthandler file.
        self.assertFalse((self.dir / diagnostics.FAULT_FILE).exists())
        self.assertIn("ValueError: bad", crashes[0].read_text(encoding="utf-8"))


class TranslationLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _text(self, name="translation.log"):
        return (self.dir / name).read_text(encoding="utf-8")

    def test_finished_run(self):
        diagnostics.start_run_log({"mode": "translate", "started": "t0"}, self.dir)
        self.assertIn("status    = running", self._text())
        diagnostics.update_run_log({"mode": "translate", "status": "finished", "lines_done": 900,
                                    "lines_total": 900, "elapsed_seconds": 600, "lines_per_min": 90.0},
                                   self.dir)
        text = self._text()
        self.assertIn("progress  = 900 / 900", text)
        self.assertIn("remaining = 0", text)
        self.assertIn("speed     = 90.0 lines/min", text)
        self.assertIn("elapsed   = 10m 00s", text)

    def test_unfinished_run_has_no_speed(self):
        diagnostics.update_run_log({"status": "cancelled", "lines_done": 120, "lines_total": 900,
                                    "lines_per_min": 50.0}, self.dir)
        text = self._text()
        self.assertIn("remaining = 780", text)
        self.assertIn("speed     = \n", text)

    def test_abrupt_end_is_marked_interrupted(self):
        diagnostics.start_run_log({"mode": "translate"}, self.dir)
        diagnostics.update_run_log({"status": "running", "lines_done": 300, "lines_total": 900}, self.dir)
        diagnostics.mark_interrupted_runs(self.dir)          # next app start
        self.assertIn("status    = interrupted", self._text())
        self.assertIn("progress  = 300 / 900", self._text())

    def test_runs_rotate_to_five_files(self):
        for i in range(7):
            diagnostics.start_run_log({"mode": f"m{i}"}, self.dir)
        names = sorted(p.name for p in self.dir.glob("translation*.log"))
        self.assertEqual(names, ["translation.log"] + [f"translation_{n}.log" for n in range(1, 5)])

    def test_worker_writes_the_log(self):
        from src.backend.editor_backend import AutoTranslateWorker
        from src.core.editor.editor_store import EditorStore
        store = EditorStore(":memory:")
        store.load_entries({"Map.json": [("p0", "はい", "dialogue")]})
        with mock.patch.object(diagnostics, "_logs_dir", return_value=self.dir), \
             mock.patch.dict(os.environ, {"RPGM_NO_DIAGNOSTICS": ""}), \
             mock.patch.object(diagnostics, "_get_json", return_value={"error": "offline"}):
            AutoTranslateWorker(store, {"engine": "pseudo", "source_lang": "ja",
                                        "target_lang": "en", "use_cache": False}).run()
        store.close()
        text = self._text()
        self.assertIn("status    = finished", text)
        self.assertIn("progress  = 1 / 1", text)
        self.assertTrue((self.dir / "system.log").exists())


if __name__ == "__main__":
    unittest.main()
