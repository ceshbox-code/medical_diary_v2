import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

_TEST_DB = os.path.join(tempfile.gettempdir(), "medical_diary_admin_stats_test.db")
os.environ["DATABASE_PATH"] = _TEST_DB

import db as db_module
db_module.DATABASE = _TEST_DB

from app import app


class AdminStatisticsApiTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                display_name TEXT,
                status TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                ip_address TEXT,
                user_agent TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE glucose_entries (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);
            CREATE TABLE blood_pressure_entries (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);
            CREATE TABLE food_entries (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);
            CREATE TABLE temperature_entries (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);
            CREATE TABLE weight_entries (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);
            CREATE TABLE medications (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);
            CREATE TABLE medication_intakes (id INTEGER PRIMARY KEY, user_id INTEGER, deleted_at TEXT);

            INSERT INTO users(id, username, display_name, status, is_admin)
            VALUES
              (1, 'admin', 'Администратор', 'active', 1),
              (2, 'user1', 'Пользователь 1', 'active', 0),
              (3, 'disabled', 'Отключённый', 'disabled', 0);

            INSERT INTO glucose_entries VALUES (1, 2, NULL), (2, 2, '2026-09-01');
            INSERT INTO blood_pressure_entries VALUES (1, 2, NULL);
            INSERT INTO food_entries VALUES (1, 2, NULL);
            INSERT INTO medications VALUES (1, 2, NULL);
            INSERT INTO medication_intakes VALUES (1, 2, NULL);

            INSERT INTO audit_log(user_id, action, created_at, details_json)
            VALUES
              (2, 'login_success', datetime('now'), '{"secret":"must-not-leak"}'),
              (2, 'login_success', datetime('now', '-10 days'), NULL),
              (2, 'export_pdf', datetime('now'), NULL),
              (2, 'ai_dynamics_summary', datetime('now'), NULL),
              (2, 'create_glucose', datetime('now'), NULL),
              (2, 'scan_medication_marking', datetime('now'), NULL),
              (2, 'login_success', datetime('now', '-400 days'), NULL);
            """
        )
        self.db.commit()

        self.client = app.test_client()
        self.patches = [
            patch("reminders.get_db", return_value=self.db),
            patch("security.get_db", return_value=self.db),
            patch("reminders.audit"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.db.close()

    def _login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = user_id
            sess["csrf_token"] = "test-csrf"

    def test_non_admin_is_forbidden(self):
        self._login_as(2)
        response = self.client.get("/api/admin/statistics?days=30")
        self.assertEqual(response.status_code, 403)

    def test_admin_gets_aggregated_statistics(self):
        self._login_as(1)
        response = self.client.get("/api/admin/statistics?days=30")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        summary = body["summary"]

        self.assertEqual(body["period_days"], 30)
        self.assertEqual(summary["users_total"], 3)
        self.assertEqual(summary["users_active"], 2)
        self.assertEqual(summary["users_disabled"], 1)
        self.assertEqual(summary["visits"], 2)
        self.assertEqual(summary["active_users"], 1)
        self.assertEqual(summary["active_days"], 1)
        self.assertEqual(summary["records_total"], 3)
        self.assertEqual(summary["medications_total"], 1)
        self.assertEqual(summary["intakes_total"], 1)
        self.assertEqual(summary["pdf_exports"], 1)
        self.assertEqual(summary["ai_requests"], 1)
        self.assertEqual(summary["activity_actions"], 3)

        user = next(item for item in body["users"] if item["id"] == 2)
        self.assertEqual(user["visits"], 2)
        self.assertEqual(user["active_days"], 1)
        self.assertEqual(user["glucose_count"], 1)
        self.assertEqual(user["vitals_count"], 1)
        self.assertEqual(user["food_count"], 1)
        self.assertEqual(user["medications_count"], 1)
        self.assertEqual(user["intakes_count"], 1)
        self.assertEqual(user["pdf_count"], 1)
        self.assertEqual(user["ai_count"], 1)

        # Сырые детали аудита, IP и User-Agent не должны утекать в ответ.
        self.assertNotIn("details_json", body)
        self.assertNotIn("ip_address", body)
        self.assertNotIn("user_agent", body)
        self.assertNotIn("must-not-leak", str(body))

    def test_invalid_period_is_rejected(self):
        self._login_as(1)
        for value in ("1", "14", "366", "abc", "-1"):
            with self.subTest(days=value):
                response = self.client.get(
                    "/api/admin/statistics?days=" + value
                )
                self.assertEqual(response.status_code, 400)

    def test_all_time_includes_old_login(self):
        self._login_as(1)
        response = self.client.get("/api/admin/statistics?days=0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["summary"]["visits"], 3)

    def test_csrf_is_not_required_for_read_only_get(self):
        self._login_as(1)
        with self.client.session_transaction() as sess:
            sess.pop("csrf_token", None)

        response = self.client.get("/api/admin/statistics?days=7")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
