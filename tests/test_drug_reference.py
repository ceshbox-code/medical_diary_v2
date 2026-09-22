import unittest

from drug_reference import _normalise_gtin
from drugdb.loader import _find_column, _normalise_gtin as loader_normalise_gtin


class DrugReferenceTests(unittest.TestCase):
    def test_normalise_13_digit_gtin(self):
        self.assertEqual(_normalise_gtin("4601234567893"), "04601234567893")

    def test_reject_invalid_gtin(self):
        with self.assertRaises(ValueError):
            _normalise_gtin("04601234567894")

    def test_loader_and_api_use_same_gtin_rules(self):
        value = "04601234567893"
        self.assertEqual(loader_normalise_gtin(value), _normalise_gtin(value))

    def test_mdlp_registration_aliases(self):
        headers = ["GTIN", "Номер регистрационного удостоверения", "Описание упаковки"]
        self.assertEqual(_find_column(headers, ["gtin"]), 0)
        self.assertEqual(_find_column(
            headers,
            ["номер ру", "номер регистрационного удостоверения", "registration_number"],
        ), 1)
        self.assertEqual(_find_column(headers, ["описание упаковки", "package_desc"]), 2)


if __name__ == "__main__":
    unittest.main()
