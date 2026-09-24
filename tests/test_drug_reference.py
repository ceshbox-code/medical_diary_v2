import sqlite3
import unittest
from unittest.mock import patch

from drug_reference import _normalise_gtin, _parse_package_quantity, lookup_drug_by_gtin


class DrugReferenceTests(unittest.TestCase):
    def test_normalise_13_digit_gtin(self):
        self.assertEqual(_normalise_gtin("4601234567893"), "04601234567893")

    def test_reject_invalid_gtin(self):
        with self.assertRaises(ValueError):
            _normalise_gtin("04601234567894")

    def test_package_quantity_requires_explicit_unit_count(self):
        self.assertEqual(_parse_package_quantity("БЛИСТЕР по 4 шт"), (4, "шт"))
        self.assertIsNone(_parse_package_quantity("ТУБА по 15.000 г")[0])

    def test_lookup_maps_prod_name_to_mnn_not_csv_inn(self):
        source = {
            "gtin": "01234567890128",
            "trade_name": "Виагра",
            "inn": "СИЛДЕНАФИЛ",
            "description": "Виагра, таблетки 50 мг",
            "dosage_form": "ТАБЛЕТКИ",
            "dosage_form_normalized": "ТАБЛЕТКИ",
            "dosage_value": "50 мг",
            "mass_volume_name": "мг",
            "manufacturer": "Производитель",
            "manufacturer_country": "РОССИЯ",
            "reg_number": "П N015875/01",
            "reg_date": "2009-08-12",
            "reg_holder": "Холдер",
            "reg_status": "Действующий",\n            "organization_inn": "83-2844990",
            "gnvlp": "Нет",
            "narcotic": "Нет",
            "is_vzn_drug": "Нет",
            "package_desc": "БЛИСТЕР по 4 шт",
        }
        with patch("drug_reference.lookup_gtin", return_value=source):
            result = lookup_drug_by_gtin("01234567890128")
        self.assertEqual(result["mnn"], "СИЛДЕНАФИЛ")
        self.assertEqual(result["inn"], "СИЛДЕНАФИЛ")
        self.assertEqual(result["organization_inn"], "83-2844990")
        self.assertEqual(result["package_quantity"], 4)

    def test_user_override_has_priority(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
          CREATE TABLE medication_barcodes (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            gtin TEXT,
            name TEXT,
            mnn TEXT,
            dosage_form TEXT,
            manufacturer TEXT,
            reg_number TEXT,
            dose_value REAL,
            dose_unit TEXT,
            intake_quantity REAL,
            intake_unit TEXT,
            package_quantity REAL,
            package_unit TEXT
          );
        """)
        db.execute(
            "INSERT INTO medication_barcodes "
            "(user_id, gtin, name, mnn, dosage_form, manufacturer, reg_number, "
            "package_quantity, package_unit) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("01234567890128", "Моё название", "Мой МНН", "таблетки", "Мой производитель",
             "РУ-1", 30, "шт"),
        )
        db.commit()
        with patch("drug_reference.get_db", return_value=db), patch(
            "drug_reference.lookup_gtin", return_value=None
        ):
            result = lookup_drug_by_gtin("01234567890128", user_id=1)
        self.assertEqual(result["source"], "user_override")
        self.assertEqual(result["trade_name"], "Моё название")
        self.assertEqual(result["mnn"], "Мой МНН")
        self.assertEqual(result["package_quantity"], 30)
        db.close()


if __name__ == "__main__":
    unittest.main()
