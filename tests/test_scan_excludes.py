"""Backup and quarantine folders must never be re-collected as game files."""
import os
import tempfile
import unittest

from src.core.translation_pipeline import TranslationPipeline


class PruneDirsTests(unittest.TestCase):
    def test_backup_folder_is_pruned(self) -> None:
        dirs = ["MapData", ".rpgm_backup", "Sub"]
        TranslationPipeline._prune_scan_dirs(dirs)
        self.assertEqual(dirs, ["MapData", "Sub"])

    def test_wolf_quarantine_is_pruned(self) -> None:
        dirs = ["BasicData", "_wolf_original"]
        TranslationPipeline._prune_scan_dirs(dirs)
        self.assertEqual(dirs, ["BasicData"])

    def test_dot_folders_are_pruned(self) -> None:
        dirs = [".git", ".cache", "Evtext"]
        TranslationPipeline._prune_scan_dirs(dirs)
        self.assertEqual(dirs, ["Evtext"])

    def test_case_insensitive(self) -> None:
        dirs = ["_WOLF_ORIGINAL", "Keep"]
        TranslationPipeline._prune_scan_dirs(dirs)
        self.assertEqual(dirs, ["Keep"])

    def test_filters_in_place_for_os_walk(self) -> None:
        """os.walk only honours an in-place edit of its dirnames list."""
        dirs = ["a", ".rpgm_backup"]
        same = TranslationPipeline._prune_scan_dirs(dirs)
        self.assertIs(same, dirs)


class CollectFilesTests(unittest.TestCase):
    """A saved project grows a .rpgm_backup inside MapData; a rescan must ignore it."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.data = os.path.join(self.root, "Data")
        mapdata = os.path.join(self.data, "MapData")
        backup = os.path.join(mapdata, ".rpgm_backup")
        os.makedirs(backup)
        for path in (os.path.join(mapdata, "Map001.mps"),
                     os.path.join(backup, "Map001.mps"),
                     os.path.join(backup, "Map001_20260101.mps")):
            with open(path, "wb") as fh:
                fh.write(b"\x00")

    def test_only_the_live_file_is_collected(self) -> None:
        pipeline = TranslationPipeline({"project_path": self.root})
        files = pipeline._collect_files(self.data)
        mps = [f for f in files if f.lower().endswith(".mps")]
        self.assertEqual(len(mps), 1, f"backup copies were collected: {mps}")
        self.assertNotIn(".rpgm_backup", mps[0])

    def test_count_is_stable_across_repeated_scans(self) -> None:
        """The reported symptom: line counts climbing after every save."""
        pipeline = TranslationPipeline({"project_path": self.root})
        first = len(pipeline._collect_files(self.data))
        second = len(pipeline._collect_files(self.data))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
