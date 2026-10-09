"""Every worker that logs must own a logger.

A missing `self.logger` surfaces only when the logging branch is reached, which
in ScanWorker's case was mid-scan - the scan aborted with
"'ScanWorker' object has no attribute 'logger'" and the project looked empty.
"""
import ast
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication

from src.backend import editor_backend as eb
from src.core.editor.editor_store import EditorStore

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

WORKERS = [
    (eb.ScanWorker, lambda st: ("/tmp", st, {})),
    (eb.AutoTranslateWorker, lambda st: (st, {})),
    (eb.SingleTranslateWorker, lambda st: (st, {}, 1)),
]


class WorkerLoggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EditorStore(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def test_each_worker_has_a_logger(self) -> None:
        import logging
        for cls, make_args in WORKERS:
            with self.subTest(worker=cls.__name__):
                worker = cls(*make_args(self.store))
                self.assertIsInstance(getattr(worker, "logger", None), logging.Logger)


class LoggerUsageTests(unittest.TestCase):
    """Static sweep: any class using self.logger must assign one in __init__."""

    @staticmethod
    def _logger_refs(class_node):
        """(reads, writes) of self.logger inside a class body."""
        reads = writes = 0
        for node in ast.walk(class_node):
            if (isinstance(node, ast.Attribute)
                    and node.attr == "logger"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                if isinstance(node.ctx, ast.Store):
                    writes += 1
                else:
                    reads += 1
        return reads, writes

    def test_no_class_uses_a_logger_it_never_assigns(self) -> None:
        tree = ast.parse(open(eb.__file__, encoding="utf-8").read())
        offenders = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            reads, writes = self._logger_refs(node)
            if reads and not writes:
                offenders.append(node.name)
        self.assertEqual(offenders, [], f"use self.logger without assigning it: {offenders}")


if __name__ == "__main__":
    unittest.main()
