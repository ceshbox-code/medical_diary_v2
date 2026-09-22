import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drugdb.loader import _find_column, _normalise_gtin


class DrugLoaderUnitTests(unittest.TestCase):
    def test_gtin_13_is_left_padded(self):
        self.assertEqual(_normalise_gtin("4601234567890"), "04601234567893")

    def test_gtin_14_is_preserved(self):
        self.assertEqual(_normalise_gtin("04601234567890"), "04601234567890")

    def test_bad_gtin_is_rejected(self):
        with self.assertRaises(ValueError):
            _normalise_gtin("123")

    def test_header_matching(self):
        self.assertEqual(_find_column(["GTIN", "Номер РУ"], ["gtin"]), 0)
        self.assertEqual(_find_column(["GTIN", "Номер РУ"], ["номер ру"]), 1)
