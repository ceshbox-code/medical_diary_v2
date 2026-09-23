import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

_TEST_DB = os.path.join(tempfile.gettempdir(), "medical_diary_scan_api_test.db")
os.environ["DATABASE_PATH"] = _TEST_DB

from app import app
from drug_reference import DrugReferenceAmbiguousError


class MedicationScanApiTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL
            );
            CREATE TABLE medication_packages (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                medication_id INTEGER
            );
            """
        )
        self.db.execute("INSERT INTO users(id, status) VALUES(1, 'active')")
        self.db.commit()

        self.client = app.test_client()
        self.patches = [
            patch("reminders.get_db", return_value=self.db),
            patch("security.get_db", return_value=self.db),
            patch("reminders.audit"),
            patch(
                "mdlp_client.MDLPClient.find_public_sgtin",
                return_value=None,
            ),
        ]
        for p in self.patches:
            p.start()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["csrf_token"] = "test-csrf"

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.db.close()

    def _scan(self):
        return self.client.post(
            "/api/medications/scan",
            json={"code": "(01)04601234567893(21)ABC1234567890"},
            headers={"X-CSRF-Token": "test-csrf"},
        )

    def test_found_returns_drug_and_status(self):
        drug = {
            "reg_number": "ЛП-000001",
            "trade_name": "Тестовый препарат",
            "inn": "test",
            "dosage_form": "таблетки",
        }
        with patch("drug_reference.lookup_drug_by_gtin", return_value=drug):
            response = self._scan()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["drug"], drug)
        self.assertEqual(body["drug_reference"]["status"], "found")
        self.assertEqual(body["marking"]["gtin"], "04601234567893")
        self.assertFalse(body["marking"]["already_registered"])

    def test_not_found_returns_explicit_status(self):
        with patch("drug_reference.lookup_drug_by_gtin", return_value=None):
            response = self._scan()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIsNone(body["drug"])
        self.assertEqual(body["drug_reference"]["status"], "not_found")

    def test_ambiguous_does_not_choose_drug(self):
        with patch(
            "drug_reference.lookup_drug_by_gtin",
            side_effect=DrugReferenceAmbiguousError("ambiguous"),
        ):
            response = self._scan()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIsNone(body["drug"])
        self.assertEqual(body["drug_reference"]["status"], "ambiguous")

    def test_unavailable_does_not_fail_scan(self):
        with patch(
            "drug_reference.lookup_drug_by_gtin",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self._scan()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIsNone(body["drug"])
        self.assertEqual(body["drug_reference"]["status"], "unavailable")

    def test_invalid_datamatrix_is_rejected(self):
        response = self.client.post(
            "/api/medications/scan",
            json={"code": "invalid"},
            headers={"X-CSRF-Token": "test-csrf"},
        )

        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["code"], "INVALID_DATAMATRIX")

    def test_csrf_is_required(self):
        response = self.client.post(
            "/api/medications/scan",
            json={"code": "(01)04601234567893(21)ABC1234567890"},
        )
        self.assertEqual(response.status_code, 403)


    def test_scan_create_intake_stock_and_duplicate_package(self):
        self.db.executescript(
            """
            CREATE TABLE medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                inn TEXT,
                dosage_form TEXT,
                manufacturer TEXT,
                reg_number TEXT,
                dose_value REAL,
                dose_unit TEXT,
                instructions TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                comment TEXT,
                days_mask INTEGER NOT NULL DEFAULT 127,
                intake_quantity REAL,
                intake_unit TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            );
            CREATE TABLE medication_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                time_of_day TEXT NOT NULL,
                UNIQUE (medication_id, time_of_day)
            );
            CREATE TABLE medication_intakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                medication_id INTEGER NOT NULL,
                medication_name TEXT NOT NULL,
                dose_value REAL,
                dose_unit TEXT,
                intake_quantity REAL,
                intake_unit TEXT,
                scheduled_at TEXT,
                status TEXT NOT NULL,
                taken_at TEXT,
                comment TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            );
            CREATE UNIQUE INDEX ux_intake_slot
                ON medication_intakes(medication_id, scheduled_at)
                WHERE scheduled_at IS NOT NULL AND deleted_at IS NULL;
            CREATE TABLE medication_packages_full (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                gtin TEXT NOT NULL,
                serial_number TEXT NOT NULL,
                batch_number TEXT,
                sgtin TEXT NOT NULL UNIQUE,
                marking_code TEXT NOT NULL,
                status TEXT,
                checked_at TEXT,
                data_json TEXT,
                source TEXT NOT NULL DEFAULT 'chestny_znak',
                package_quantity REAL,
                package_unit TEXT,
                remaining_quantity REAL,
                purchase_date TEXT,
                expiry_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        self.db.execute("DROP TABLE medication_packages")
        self.db.execute("ALTER TABLE medication_packages_full RENAME TO medication_packages")
        self.db.commit()

        drug = {
            "reg_number": "ЛП-000001",
            "trade_name": "Тестовый препарат",
            "inn": "test",
            "dosage_form": "таблетки",
            "manufacturer": "ТестФарм",
            "package_quantity": 10,
            "package_unit": "шт",
        }
        marking = {
            "raw": "(01)04601234567893(21)ABC1234567890",
            "gtin": "04601234567893",
            "serial_number": "ABC1234567890",
            "sgtin": "04601234567893ABC1234567890",
            "batch_number": None,
            "expiry_date": None,
            "production_date": None,
        }
        payload = {
            "name": drug["trade_name"],
            "inn": drug["inn"],
            "dosage_form": drug["dosage_form"],
            "manufacturer": drug["manufacturer"],
            "reg_number": drug["reg_number"],
            "intake_quantity": 1,
            "intake_unit": "шт",
            "package_quantity": 10,
            "package_unit": "шт",
            "marking": marking,
            "purchase_date": "2026-09-01",
        }

        with patch("drug_reference.lookup_drug_by_gtin", return_value=drug), patch(
            "mdlp_client.MDLPClient.find_public_sgtin", return_value=None
        ):
            response = self.client.post(
                "/api/medications",
                json=payload,
                headers={"X-CSRF-Token": "test-csrf"},
            )

        self.assertEqual(response.status_code, 200)
        med_id = response.get_json()["id"]

        package = self.db.execute(
            "SELECT gtin, serial_number, sgtin, package_quantity, package_unit, purchase_date "
            "FROM medication_packages WHERE medication_id = ?",
            (med_id,),
        ).fetchone()
        self.assertEqual(tuple(package), (
            "04601234567893",
            "ABC1234567890",
            "04601234567893ABC1234567890",
            10.0,
            "шт",
            "2026-09-01",
        ))

        stock_before = self.client.get("/api/medications").get_json()["medications"][0]["stock"]
        self.assertEqual(stock_before["package_count"], 1)
        self.assertEqual(stock_before["remaining_quantity"], 10.0)
        self.assertEqual(stock_before["unit"], "шт")

        intake_response = self.client.post(
            "/api/medication-intakes",
            json={
                "medication_id": med_id,
                "status": "taken",
                "taken_at": "2026-09-01 12:00:00",
                "comment": "тест",
            },
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(intake_response.status_code, 200)

        stock_after = self.client.get("/api/medications").get_json()["medications"][0]["stock"]
        self.assertEqual(stock_after["remaining_quantity"], 9.0)
        self.assertEqual(stock_after["unit"], "шт")

        duplicate_response = self.client.post(
            "/api/medications",
            json=payload,
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(duplicate_response.status_code, 409)
        self.assertEqual(
            duplicate_response.get_json()["error"],
            "Эта упаковка «Честный знак» уже привязана к вашему лекарству",
        )
        package_count = self.db.execute(
            "SELECT COUNT(*) FROM medication_packages WHERE user_id = 1"
        ).fetchone()[0]
        self.assertEqual(package_count, 1)


if __name__ == "__main__":
    unittest.main()
