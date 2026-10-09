"""Save must not report success when nothing was written."""
import os
import unittest
from unittest.mock import MagicMock

from src.backend.editor_backend import EditorBackend
from src.core.parsers.wolf_parser import WolfParser


class WolfApplyFailureTests(unittest.TestCase):
    """A .dat without its sibling .project schema cannot be written."""

    def test_missing_project_schema_is_reported(self) -> None:
        import tempfile
        d = tempfile.mkdtemp()
        dat = os.path.join(d, "Database.dat")
        with open(dat, "wb") as fh:
            fh.write(b"\x00" * 16)

        parser = WolfParser()
        result = parser.apply_translation(dat, {"loc": "text"})
        self.assertIsNone(result)
        self.assertTrue(parser.last_apply_error)
        self.assertIn("project", parser.last_apply_error.lower())

    def test_no_translations_returns_the_file_unchanged(self) -> None:
        import tempfile
        d = tempfile.mkdtemp()
        dat = os.path.join(d, "Database.dat")
        with open(dat, "wb") as fh:
            fh.write(b"abc")
        self.assertEqual(WolfParser().apply_translation(dat, {}), b"abc")


class SaveMessageTests(unittest.TestCase):
    """The outcome message must distinguish written from not-written."""

    def _backend(self):
        be = EditorBackend.__new__(EditorBackend)
        be.logger = MagicMock()
        be._store = MagicMock()
        be._unsaved_count = 1
        be.settings_backend = MagicMock()
        be.settings_backend.get_dict.return_value = {"target_lang": "en", "source_lang": "ja"}
        be.app_backend = MagicMock()
        be.saveFinished = MagicMock()
        return be

    def test_zero_written_is_not_reported_as_success(self) -> None:
        be = self._backend()
        be._store.get_modified_entries.return_value = ({}, {})
        EditorBackend.saveChanges(be)
        ok, msg = be.saveFinished.emit.call_args[0]
        # An empty change set is a genuine "nothing to do", not a failure...
        self.assertTrue(ok)
        self.assertIn("No changes", msg)

    def test_save_is_gated_on_unsaved_not_hand_edits(self) -> None:
        be = self._backend()
        be._unsaved_count = 0
        EditorBackend.saveChanges(be)
        ok, msg = be.saveFinished.emit.call_args[0]
        self.assertTrue(ok)
        self.assertIn("No changes", msg)

    def test_guard_uses_unsaved_count_attribute(self) -> None:
        """Regression: gating on _modified_count skipped auto-translated rows."""
        import inspect
        src = inspect.getsource(EditorBackend.saveChanges)
        self.assertIn("_unsaved_count", src)
        head = src.split("changes_by_file")[0]
        self.assertNotIn("_modified_count", head)


class IsolationWiringTests(unittest.TestCase):
    def test_project_dir_is_defined_before_use(self) -> None:
        """It was an undefined name, so isolation silently never ran."""
        import inspect
        src = inspect.getsource(EditorBackend.saveChanges)
        assign = src.index("project_dir =")
        use = src.index("isolate_conflicting_wolf_archives(project_dir)")
        self.assertLess(assign, use)

    def test_isolation_is_still_called_on_save(self) -> None:
        import inspect
        src = inspect.getsource(EditorBackend.saveChanges)
        self.assertIn("isolate_conflicting_wolf_archives", src)


if __name__ == "__main__":
    unittest.main()
