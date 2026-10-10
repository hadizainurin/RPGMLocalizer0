"""A UTF-8 WOLF file must be written back as UTF-8.

The writers forced every file below v3.5 to CP932 ("WOLF 2.x cannot read
UTF-8"). WOLF 3.x games ship UTF-8 files with pre-3.5 version bytes (False
Myth 2: CommonEvent 0x91, CDataBase 0xC3, both flagged UTF-8). Saving one of
them downgraded it to CP932 while the untouched files stayed UTF-8, so the
common event's field name 現在値 no longer matched the database's, and the game
stopped with "[DB操作] タイプ0 データ0 には以下の項目名は存在しません 現在値".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.parsers.wolf_binary import (  # noqa: E402
    DataRecord,
    DbType,
    Field,
    WolfCommonEvents,
    WolfDatabase,
)

PRE_V35_DAT = 0xC3
PRE_V35_CE = 0x91
CE_TERMINATOR = 0x8F


def _db(is_utf8: bool) -> WolfDatabase:
    fields = [
        Field(name="現在値", index_info=1000),
        Field(name="MAX", index_info=1001),
        Field(name="ブラストコスト", index_info=2000),
    ]
    t = DbType(
        name="アクションゲージ",
        fields=fields,
        data=[DataRecord(name="ACTゲージ", int_values=[1, 2], string_values=["説明"])],
        description="",
        field_type_list_size=len(fields),
    )
    return WolfDatabase([t], version=PRE_V35_DAT, is_utf8=is_utf8)


class DatabaseEncodingTests(unittest.TestCase):
    def test_utf8_database_stays_utf8(self):
        proj, dat = _db(is_utf8=True).to_project_and_dat_bytes()
        self.assertIn("現在値".encode("utf-8"), proj)
        self.assertNotIn("現在値".encode("cp932"), proj)
        self.assertTrue(WolfDatabase.from_bytes(proj, dat).is_utf8)

    def test_project_is_read_with_the_dat_encoding(self):
        # 現在値 in UTF-8 is also valid CP932 (迴ｾ蝨ｨ蛟､): reading the project
        # as CP932 produced mojibake rather than an error.
        proj, dat = _db(is_utf8=True).to_project_and_dat_bytes()
        back = WolfDatabase.from_bytes(proj, dat)
        self.assertEqual([f.name for f in back.types[0].fields],
                         ["現在値", "MAX", "ブラストコスト"])
        self.assertEqual(back.types[0].data[0].name, "ACTゲージ")

    def test_translated_utf8_database_round_trips(self):
        proj, dat = _db(is_utf8=True).to_project_and_dat_bytes()
        db = WolfDatabase.from_bytes(proj, dat)
        db.types[0].data[0].name = "ACT Gauge — “x”"
        proj2, dat2 = db.to_project_and_dat_bytes()
        back = WolfDatabase.from_bytes(proj2, dat2)
        self.assertTrue(back.is_utf8)
        self.assertEqual(back.types[0].fields[0].name, "現在値")
        self.assertEqual(back.types[0].data[0].name, "ACT Gauge — “x”")

    def test_cp932_database_stays_cp932(self):
        proj, dat = _db(is_utf8=False).to_project_and_dat_bytes()
        self.assertIn("現在値".encode("cp932"), proj)
        self.assertFalse(WolfDatabase.from_bytes(proj, dat).is_utf8)

    def test_dat_field_list_is_written_verbatim(self):
        # The .dat may index fewer fields than the .project names; writing one
        # entry per .project field added phantom columns.
        proj, dat = _db(is_utf8=True).to_project_and_dat_bytes()
        db = WolfDatabase.from_bytes(proj, dat)
        db.types[0].fields.append(Field(name="未使用"))
        _, dat2 = db.to_project_and_dat_bytes()
        self.assertEqual(dat2, dat)


class CommonEventEncodingTests(unittest.TestCase):
    def test_utf8_common_events_stay_utf8(self):
        ce = WolfCommonEvents([], PRE_V35_CE, CE_TERMINATOR, True)
        self.assertTrue(WolfCommonEvents.from_bytes(ce.to_bytes()).is_utf8)

    def test_cp932_common_events_stay_cp932(self):
        ce = WolfCommonEvents([], PRE_V35_CE, CE_TERMINATOR, False)
        self.assertFalse(WolfCommonEvents.from_bytes(ce.to_bytes()).is_utf8)


if __name__ == "__main__":
    unittest.main()
