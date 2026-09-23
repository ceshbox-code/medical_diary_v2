import io
import os
import unittest
import zipfile
from unittest.mock import patch

import psycopg
from openpyxl import Workbook

from drug_reference import DrugReferenceAmbiguousError, lookup_drug_by_gtin
from drugdb import loader


DSN = os.getenv("DRUG_DB_DSN", "").strip()


@unittest.skipUnless(DSN, "DRUG_DB_DSN is not configured")
class DrugDbIntegrationTests(unittest.TestCase):
    GTIN = "04601234567893"

    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(DSN)
        with cls.conn.cursor() as cur:
            with open("drugdb/schema.sql", "r", encoding="utf-8") as fh:
                cur.execute(fh.read())
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "TRUNCATE drug_gtin_pending, drug_gtins, drugs, drug_import_runs, "
                "drug_source_state RESTART IDENTITY CASCADE"
            )
        self.conn.commit()

    def _grls_zip(self, rows):
        wb = Workbook()
        ws = wb.active
        ws.append([
            "Номер регистрационного удостоверения",
            "Торговое наименование",
            "МНН",
            "Форма выпуска",
            "Дозировка",
            "Производитель",
            "Юридическое лицо, на имя которого выдано регистрационное удостоверение",
            "Дата регистрации",
            "Дата окончания действия регистрационного удостоверения",
            "Сведения о стадиях производства",
            "Фармакотерапевтическая группа",
            "Наличие лекарственного препарата в перечне ЖНВЛП",
            "Наличие в лекарственном препарате наркотических средств, психотропных веществ",
            "Статус признания лекарственного препарата орфанным",
            "Статус",
        ])
        for row in rows:
            ws.append(row)
        xlsx = io.BytesIO()
        wb.save(xlsx)
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("ГРЛС_действует.xlsx", xlsx.getvalue())
        return result.getvalue()

    def _mdlp_csv(self, reg_number, package="таблетки 10 шт"):
        return (
            "GTIN;Номер регистрационного удостоверения;Описание упаковки\n"
            f"{self.GTIN};{reg_number};{package}\n"
        ).encode("utf-8")

    def _count(self, table):
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]

    def test_stale_running_import_is_recovered(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drug_import_runs(
                    source, started_at, status
                )
                VALUES('mdlp', NOW() - INTERVAL '4 hours', 'running')
                """
            )
        self.conn.commit()

        with patch.object(loader, "DSN", DSN):
            loader.load_mdlp(self._mdlp_csv("ЛП-000001"))

        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, finished_at, error_text
                FROM drug_import_runs
                WHERE source='mdlp'
                ORDER BY id
                """
            )
            rows = cur.fetchall()

        self.assertEqual(rows[0][0], "error")
        self.assertIsNotNone(rows[0][1])
        self.assertEqual(rows[0][2], "stale running import recovered")
        self.assertEqual(rows[1][0], "success")

    def test_mdlp_before_grls_is_reconciled_and_idempotent(self):
        with patch.object(loader, "DSN", DSN):
            self.assertEqual(loader.load_mdlp(self._mdlp_csv("ЛП-000001")), (1, 0, 1))
            self.assertEqual(self._count("drug_gtin_pending"), 1)
            self.assertEqual(
                loader.load_grls(
                    self._grls_zip([(
                        "ЛП-000001", "ТестПрепарат", "ТестМНН", "таблетки",
                        "10 мг", "ТестФарм", "ТестХолдер", "01.01.2025",
                        "01.01.2030", "Россия", "Тестовая группа", "да",
                        "нет", "нет", "действует",
                    )])
                ),
                (1, 1, 0),
            )
            self.assertEqual(self._count("drug_gtin_pending"), 0)
            self.assertEqual(self._count("drug_gtins"), 1)

            loader.load_mdlp(self._mdlp_csv("ЛП-000001"))
            loader.load_grls(
                self._grls_zip([(
                    "ЛП-000001", "ТестПрепарат", "ТестМНН", "таблетки",
                    "10 мг", "ТестФарм", "ТестХолдер", "01.01.2025",
                    "01.01.2030", "Россия", "Тестовая группа", "да",
                    "нет", "нет", "действует",
                )])
            )
            self.assertEqual(self._count("drugs"), 1)
            self.assertEqual(self._count("drug_gtins"), 1)

            with patch("drug_reference.DSN", DSN):
                result = lookup_drug_by_gtin(self.GTIN)
            self.assertEqual(result["reg_number"], "ЛП-000001")
            self.assertEqual(result["trade_name"], "ТестПрепарат")
            self.assertEqual(result["inn"], "ТестМНН")
            self.assertEqual(result["manufacturer"], "ТестФарм")
            self.assertEqual(result["package_quantity"], 10)
            self.assertEqual(result["package_unit"], "шт")

    def test_one_gtin_mapped_to_two_active_records_is_not_selected_arbitrarily(self):
        with patch.object(loader, "DSN", DSN):
            loader.load_grls(
                self._grls_zip([
                    (
                        "ЛП-000001", "Препарат А", "МНН А", "таблетки",
                        "10 мг", "Фарм А", "Холдер А", "01.01.2025",
                        "01.01.2030", "Россия", "Группа А", "да",
                        "нет", "нет", "действует",
                    ),
                    (
                        "ЛП-000002", "Препарат Б", "МНН Б", "таблетки",
                        "10 мг", "Фарм Б", "Холдер Б", "01.01.2025",
                        "01.01.2030", "Россия", "Группа Б", "нет",
                        "нет", "нет", "действует",
                    ),
                ])
            )
            loader.load_mdlp(
                (
                    "GTIN;Номер регистрационного удостоверения\n"
                    f"{self.GTIN};ЛП-000001\n"
                    f"{self.GTIN};ЛП-000002\n"
                ).encode("utf-8")
            )

            with patch("drug_reference.DSN", DSN):
                with self.assertRaises(DrugReferenceAmbiguousError):
                    lookup_drug_by_gtin(self.GTIN)


if __name__ == "__main__":
    unittest.main()
