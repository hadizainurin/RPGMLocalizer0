"""WOLF projects are identified by the title in Game.dat, not the folder name.

WOLF games ship a generic Game.exe, so the id fell back to the folder name and
a copy of the game in a differently named folder got an empty cache - Patch
from Cache then had nothing to patch with.
"""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils import app_paths  # noqa: E402


def _wolf_string(text: str, enc: str) -> bytes:
    raw = text.encode(enc) + b"\x00"
    return struct.pack("<i", len(raw)) + raw


def _game_dat(title: str, utf8: bool = True) -> bytes:
    enc = "utf-8" if utf8 else "cp932"
    magic = b"\x00W\x00\x00OL\x00FM" + (b"U" if utf8 else b"\x00")
    settings = bytes(range(35))
    strings = [title, "0000-0000", "ＭＳ ゴシック"]
    body = struct.pack("<i", len(settings)) + settings + struct.pack("<i", len(strings))
    body += b"".join(_wolf_string(s, enc) for s in strings)
    return magic + body


class WolfTitleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "appdata"
        self.data_dir.mkdir()
        self.patcher = mock.patch.object(app_paths, "get_data_dir", return_value=self.data_dir)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def _game(self, folder: str, title: str, utf8: bool = True, layout=("Data", "BasicData")) -> Path:
        game = self.root / folder
        target = game.joinpath(*layout)
        target.mkdir(parents=True)
        (target / "Game.dat").write_bytes(_game_dat(title, utf8))
        return game

    def test_title_is_read_from_game_dat(self) -> None:
        game = self._game("FalseMyth2_fresh_copy", "FalseMyth2")
        self.assertEqual(app_paths.get_project_id(game), "FalseMyth2")

    def test_two_copies_in_different_folders_share_an_id(self) -> None:
        a = self._game("FalseMyth2", "FalseMyth2")
        b = self._game("GameDataNewFresh", "FalseMyth2")
        self.assertEqual(app_paths.get_project_id(a), app_paths.get_project_id(b))

    def test_cp932_title(self) -> None:
        game = self._game("x", "偽りの神話", utf8=False)
        self.assertEqual(app_paths.get_project_id(game), "偽りの神話")

    def test_lowercase_folders_and_basicdata_root(self) -> None:
        game = self._game("y", "TitleY", layout=("data", "basicdata"))
        self.assertEqual(app_paths.get_project_id(game), "TitleY")
        game2 = self._game("z", "TitleZ", layout=())
        self.assertEqual(app_paths.get_project_id(game2), "TitleZ")

    def test_archived_game_keeps_folder_name(self) -> None:
        game = self.root / "Archived Game"
        (game / "Data").mkdir(parents=True)
        (game / "Data" / "BasicData.wolf").write_bytes(b"\x00" * 64)
        self.assertEqual(app_paths.get_project_id(game), "Archived Game")

    def test_garbage_game_dat_is_ignored(self) -> None:
        game = self.root / "Broken"
        (game / "Data" / "BasicData").mkdir(parents=True)
        (game / "Data" / "BasicData" / "Game.dat").write_bytes(b"not a wolf file at all......")
        self.assertEqual(app_paths.get_project_id(game), "Broken")

    def test_existing_folder_name_cache_is_adopted(self) -> None:
        legacy = self.data_dir / "cache" / "MyOldFolder"
        legacy.mkdir(parents=True)
        (legacy / "editor_strings.db").write_bytes(b"db")
        game = self._game("MyOldFolder", "RealTitle")
        self.assertEqual(app_paths.get_project_id(game), "RealTitle")
        self.assertTrue((self.data_dir / "cache" / "RealTitle" / "editor_strings.db").is_file())
        self.assertFalse(legacy.exists())

    def test_existing_title_cache_is_never_overwritten(self) -> None:
        for name in ("MyOldFolder", "RealTitle"):
            (self.data_dir / "cache" / name).mkdir(parents=True)
            (self.data_dir / "cache" / name / f"{name}.db").write_bytes(b"db")
        game = self._game("MyOldFolder", "RealTitle")
        self.assertEqual(app_paths.get_project_id(game), "RealTitle")
        self.assertTrue((self.data_dir / "cache" / "MyOldFolder" / "MyOldFolder.db").is_file())
        self.assertFalse((self.data_dir / "cache" / "RealTitle" / "MyOldFolder.db").exists())

    def test_legacy_id_kept_if_the_cache_cannot_be_moved(self) -> None:
        (self.data_dir / "cache" / "MyOldFolder").mkdir(parents=True)
        (self.data_dir / "cache" / "MyOldFolder" / "editor_strings.db").write_bytes(b"db")
        game = self._game("MyOldFolder", "RealTitle")
        with mock.patch.object(Path, "rename", side_effect=PermissionError("in use")):
            self.assertEqual(app_paths.get_project_id(game), "MyOldFolder")


if __name__ == "__main__":
    unittest.main()


class WolfConfigExeTests(unittest.TestCase):
    """WOLF ships Config.exe; it was taken as the title, so every WOLF game
    shared one "Config" cache. That cache is copied (not moved) to the game's
    real id, because other games may be filed under it too."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "appdata"
        self.patcher = mock.patch.object(app_paths, "get_data_dir", return_value=self.data_dir)
        self.patcher.start()
        shared = self.data_dir / "cache" / "Config"
        shared.mkdir(parents=True)
        (shared / "translation_cache.json").write_text("{}")

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def _game(self, folder: str, title: str | None) -> Path:
        game = self.root / folder
        basic = game / "Data" / "BasicData"
        basic.mkdir(parents=True)
        (game / "Game.exe").write_bytes(b"MZ")
        (game / "Config.exe").write_bytes(b"MZ")
        if title:
            (basic / "Game.dat").write_bytes(_game_dat(title))
        return game

    def test_config_exe_is_not_a_title(self) -> None:
        game = self._game("SomeWolfGame", None)
        self.assertNotEqual(app_paths.get_project_id(game), "Config")

    def test_shared_config_cache_is_copied_to_the_title(self) -> None:
        game = self._game("FalseMyth2", "FalseMyth2")
        self.assertEqual(app_paths.get_project_id(game), "FalseMyth2")
        self.assertTrue((self.data_dir / "cache" / "FalseMyth2" / "translation_cache.json").is_file())
        self.assertTrue((self.data_dir / "cache" / "Config" / "translation_cache.json").is_file())

    def test_folder_name_cache_wins_over_config(self) -> None:
        own = self.data_dir / "cache" / "MyFolder"
        own.mkdir(parents=True)
        (own / "mine.txt").write_text("x")
        game = self._game("MyFolder", "RealTitle")
        self.assertEqual(app_paths.get_project_id(game), "RealTitle")
        self.assertTrue((self.data_dir / "cache" / "RealTitle" / "mine.txt").is_file())


class EmptyTitleFolderTests(unittest.TestCase):
    """get_cache_dir creates empty folders on first use, so an empty title
    folder must not block adopting the real cache."""

    def test_empty_title_folder_does_not_block_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "appdata"
            (data_dir / "cache" / "Config").mkdir(parents=True)
            (data_dir / "cache" / "Config" / "translation_cache.json").write_text("{}")
            (data_dir / "cache" / "FalseMyth2" / "en").mkdir(parents=True)
            game = root / "FalseMyth2"
            (game / "Data" / "BasicData").mkdir(parents=True)
            (game / "Data" / "BasicData" / "Game.dat").write_bytes(_game_dat("FalseMyth2"))
            (game / "Config.exe").write_bytes(b"MZ")
            with mock.patch.object(app_paths, "get_data_dir", return_value=data_dir):
                self.assertEqual(app_paths.get_project_id(game), "FalseMyth2")
            self.assertTrue((data_dir / "cache" / "FalseMyth2" / "translation_cache.json").is_file())
