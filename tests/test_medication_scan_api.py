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


if __name__ == "__main__":
    unittest.main()
