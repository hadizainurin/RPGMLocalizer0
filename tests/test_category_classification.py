"""WOLF commands that show text to the player belong under Dialogue."""
import unittest

from src.core.editor.editor_store import classify_category
from src.core.parsers.wolf_parser import wolf_tag_for
from src.core.parsers.wolf_binary import (
    CID_MESSAGE, CID_CHOICES, CID_ERROR_MESSAGE, CID_STRING_OP,
    CID_PICTURE_TEXT, CID_BATTLE_MESSAGE, CID_DB_ACCESS, command_text_slots,
)


class WolfTagTests(unittest.TestCase):
    def test_every_text_carrying_command_is_dialogue(self) -> None:
        """If command_text_slots calls it player-facing, it must not be 'system'."""
        for cid in (CID_MESSAGE, CID_CHOICES, CID_ERROR_MESSAGE,
                    CID_STRING_OP, CID_PICTURE_TEXT, CID_BATTLE_MESSAGE):
            with self.subTest(cid=cid):
                self.assertEqual(
                    classify_category("CommonEvent.dat", wolf_tag_for(cid)), "dialogues")

    def test_string_op_is_the_reported_case(self) -> None:
        """A line like 男の子「パパ…ごめんなさい」 came through CID 122/150."""
        self.assertEqual(classify_category("CommonEvent.dat", wolf_tag_for(CID_STRING_OP)),
                         "dialogues")
        self.assertEqual(classify_category("CommonEvent.dat", wolf_tag_for(CID_PICTURE_TEXT)),
                         "dialogues")

    def test_db_access_stays_system(self) -> None:
        self.assertEqual(classify_category("CommonEvent.dat", wolf_tag_for(CID_DB_ACCESS)),
                         "system")

    def test_unknown_commands_stay_system(self) -> None:
        self.assertEqual(classify_category("BasicData.dat", wolf_tag_for(9999)), "system")


class TagPrecedenceTests(unittest.TestCase):
    def test_exact_tag_beats_substring_sniffing(self) -> None:
        """'system_message' is a message; the old order called it a system term."""
        self.assertEqual(classify_category("Map001.mps", "message"), "dialogues")
        self.assertEqual(classify_category("System.json", "dialogue"), "dialogues")

    def test_file_name_fallback_still_applies(self) -> None:
        self.assertEqual(classify_category("Map001.json", ""), "dialogues")
        self.assertEqual(classify_category("Actors.json", ""), "actors")
        self.assertEqual(classify_category("Items.json", ""), "items")
        self.assertEqual(classify_category("System.json", ""), "system")
        self.assertEqual(classify_category("plugins.js", ""), "plugins")

    def test_genuine_system_tags_are_untouched(self) -> None:
        self.assertEqual(classify_category("BasicData.dat", "system"), "system")


class SlotCoverageTests(unittest.TestCase):
    """Guard the two lists against drifting apart."""

    class _Cmd:
        def __init__(self, cid, n=5):
            self.cid = cid
            self.string_args = ["x"] * n
            self.args = [0] * 5

    def test_text_carrying_commands_are_not_tagged_system(self) -> None:
        for cid in (CID_MESSAGE, CID_CHOICES, CID_ERROR_MESSAGE,
                    CID_STRING_OP, CID_PICTURE_TEXT, CID_BATTLE_MESSAGE):
            with self.subTest(cid=cid):
                self.assertTrue(command_text_slots(self._Cmd(cid)))
                self.assertNotEqual(wolf_tag_for(cid), "system")


if __name__ == "__main__":
    unittest.main()
