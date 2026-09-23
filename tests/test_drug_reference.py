import unittest
from datetime import datetime
from unittest.mock import patch

from drug_reference import _normalise_gtin
from drugdb.loader import _csv_reader, _find_column, _normalise_gtin as loader_normalise_gtin
from drugdb import runner


class DrugReferenceTests(unittest.TestCase):
    def test_normalise_13_digit_gtin(self):
        self.assertEqual(_normalise_gtin("4601234567893"), "04601234567893")

    def test_reject_invalid_gtin(self):
        with self.assertRaises(ValueError):
            _normalise_gtin("04601234567894")

    def test_loader_and_api_use_same_gtin_rules(self):
        value = "04601234567893"
        self.assertEqual(loader_normalise_gtin(value), _normalise_gtin(value))

    def test_runner_does_not_require_explicit_mdlp_url(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(runner, "main") as main:
                runner._run("mdlp")
                main.assert_called_once()

    def test_runner_skips_grls_without_url(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(runner, "main") as main:
                runner._run("grls")
                main.assert_not_called()

    def test_runner_calculates_next_grls_run_at_configured_time(self):
        with patch.object(runner, "TZ_NAME", "Europe/Moscow"), patch.object(
            runner, "RUN_HOUR", 3
        ), patch.object(runner, "RUN_MINUTE", 0):
            now = datetime.fromisoformat("2026-09-22T01:00:00+03:00")
            self.assertEqual(runner._seconds_until_next_grls(now), 7200)

    def test_runner_calculates_next_day_after_scheduled_time(self):
        with patch.object(runner, "TZ_NAME", "Europe/Moscow"), patch.object(
            runner, "RUN_HOUR", 3
        ), patch.object(runner, "RUN_MINUTE", 0):
            now = datetime.fromisoformat("2026-09-22T04:00:00+03:00")
            self.assertEqual(runner._seconds_until_next_grls(now), 23 * 3600)

    def test_mdlp_csv_finds_header_after_metadata_line(self):
        data = (
            "Дата публикации;2026-09-23\\n"
            "GTIN;Номер регистрационного удостоверения;Описание упаковки\\n"
            "04601234567893;ЛП-000001;таблетки 10 шт\\n"
        ).encode("utf-8")
        headers, reader = _csv_reader(data)
        self.assertEqual(headers[0], "GTIN")
        self.assertEqual(next(reader)[0], "04601234567893")

    def test_mdlp_csv_supports_cp1251(self):
        data = (
            "GTIN;Номер РУ\\n"
            "04601234567893;ЛП-000001\\n"
        ).encode("cp1251")
        headers, reader = _csv_reader(data)
        self.assertEqual(headers[1], "Номер РУ")
        self.assertEqual(next(reader)[1], "ЛП-000001")

    def test_mdlp_registration_aliases(self):
        headers = ["GTIN", "Номер регистрационного удостоверения", "Описание упаковки"]
        self.assertEqual(_find_column(headers, ["gtin"]), 0)
        self.assertEqual(
            _find_column(
                headers,
                ["номер ру", "номер регистрационного удостоверения", "registration_number"],
            ),
            1,
        )
        self.assertEqual(_find_column(headers, ["описание упаковки", "package_desc"]), 2)


if __name__ == "__main__":
    unittest.main()
