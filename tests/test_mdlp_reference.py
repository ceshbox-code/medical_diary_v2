import os
import tempfile
import unittest
import sqlite3
from unittest import mock

from mdlp_import import EXPECTED_COLUMNS, import_csv
from mdlp_reference import lookup_gtin


def _csv(rows):
    header = ",".join('"' + c + '"' for c in EXPECTED_COLUMNS)
    body = []
    for row in rows:
        body.append(",".join('"' + str(row.get(c, "")).replace('"', '""') + '"' for c in EXPECTED_COLUMNS))
    return header + "\n" + "\n".join(body) + "\n"


class MDLPReferenceTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_import_and_lookup_preserve_mnn_not_organization_inn(self):
        row = {
            "gtin": "01234567890128",
            "prod_name": "СИЛДЕНАФИЛ",
            "prod_desc": "Виагра, таблетки 50 мг",
            "prod_sell_name": "Виагра",
            "reg_id": "П N015875/01",
            "reg_date": "2009-08-12",
            "reg_holder": "Холдер",
            "prod_d_name": "50 мг",
            "mass_volume_name": "мг",
            "prod_form_name": "ТАБЛЕТКИ",
            "prod_form_norm_name": "ТАБЛЕТКИ ПОКРЫТЫЕ",
            "prod_pack_1_desc": "БЛИСТЕР по 4 шт",
            "prod_pack_1_2": "1",
            "prod_pack_1_name": "БЛИСТЕР",
            "prod_pack_1_size": "4",
            "glf_name": "Производитель",
            "glf_country": "РОССИЯ",
            "inn": "83-2844990",
            "reg_status": "Действующий",
        }
        self.assertEqual(import_csv(_csv([row]), self.path), 1)
import mdlp_reference
        with mock.patch.object(mdlp_reference, "REFERENCE_DB", self.path):
            result = mdlp_reference.lookup_gtin("01234567890128")
        self.assertEqual(result["inn"], "СИЛДЕНАФИЛ")
        self.assertEqual(result["trade_name"], "Виагра")
        self.assertEqual(result["reg_holder"], "Холдер")
        self.assertEqual(result["package_desc"], "БЛИСТЕР по 4 шт")

    def test_duplicate_gtin_is_rejected_without_partial_import(self):
        row = {"gtin": "01234567890128", "prod_name": "A", "prod_sell_name": "A", "reg_status": "Действующий"}
        with self.assertRaises(ValueError):
            import_csv(_csv([row, row]), self.path)
        import mdlp_reference
        with unittest.mock.patch.object(mdlp_reference, "REFERENCE_DB", self.path):
            self.assertIsNone(mdlp_reference.lookup_gtin("01234567890128"))


if __name__ == "__main__":
    unittest.main()
