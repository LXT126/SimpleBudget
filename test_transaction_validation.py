import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as application
from transaction_validation import validate_transaction


class TransactionValidationTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.db_path = Path(temp_dir.name) / "test.db"

        with closing(self.connect()) as conn, conn:
            conn.execute(
                """CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL
                )"""
            )
            cursor = conn.execute(
                """INSERT INTO transactions (date, category, amount, type)
                   VALUES (?, ?, ?, ?)""",
                ("2026-11-18", "Groceries", "25.50", "expense"),
            )
            self.transaction_id = cursor.lastrowid

        connection_patch = patch.object(
            application, "get_db_connection", self.connect
        )
        connection_patch.start()
        self.addCleanup(connection_patch.stop)
        self.client = application.app.test_client()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def valid_data(self, **changes):
        data = {
            "date": "2026-11-18",
            "category": "Groceries",
            "amount": "12.50",
            "type": "expense",
        }
        data.update(changes)
        return data

    def rows(self):
        with closing(self.connect()) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM transactions ORDER BY id"
                ).fetchall()
            ]

    def assert_rejected(self, data, message):
        before = self.rows()
        for endpoint in (
            "/add",
            f"/edit/{self.transaction_id}",
        ):
            with self.subTest(endpoint=endpoint, data=data):
                response = self.client.post(endpoint, data=data)
                self.assertEqual(response.status_code, 400)
                self.assertIn(
                    message, response.get_data(as_text=True)
                )
                self.assertEqual(self.rows(), before)

    def test_valid_add(self):
        response = self.client.post("/add", data=self.valid_data())
        self.assertEqual(response.status_code, 302)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["amount"], 12.50)
        self.assertEqual(rows[-1]["type"], "expense")

    def test_valid_edit(self):
        response = self.client.post(
            f"/edit/{self.transaction_id}",
            data=self.valid_data(
                date="2026-12-01",
                category="Salary",
                amount="100.25",
                type="income",
            ),
        )
        self.assertEqual(response.status_code, 302)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-12-01")
        self.assertEqual(rows[0]["category"], "Salary")
        self.assertEqual(rows[0]["amount"], 100.25)
        self.assertEqual(rows[0]["type"], "income")

    def test_invalid_dates(self):
        for value in (
            "",
            "2026-02-30",
            "2025-02-29",
            "0000-01-01",
            "2026-13-01",
            "2026-1-01",
            "20261118",
            "hello",
        ):
            with self.subTest(date=value):
                self.assert_rejected(
                    self.valid_data(date=value),
                    "Enter a valid",
                )

    def test_valid_leap_day(self):
        response = self.client.post(
            "/add",
            data=self.valid_data(date="2024-02-29"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.rows()[-1]["date"], "2024-02-29")

    def test_empty_categories(self):
        for value in ("", "   "):
            with self.subTest(category=value):
                self.assert_rejected(
                    self.valid_data(category=value),
                    "Choose a category.",
                )

    def test_invalid_amounts(self):
        for value in (
            "",
            "-1",
            "0",
            "0.00",
            "1.234",
            "abc",
            "NaN",
            "Infinity",
            "1e3",
            "1,000",
        ):
            with self.subTest(amount=value):
                self.assert_rejected(
                    self.valid_data(amount=value),
                    "Please correct the following errors:",
                )

    def test_invalid_types(self):
        for value in ("", "transfer", "EXPENSE"):
            with self.subTest(kind=value):
                self.assert_rejected(
                    self.valid_data(type=value),
                    "Choose expense or income.",
                )

    def test_missing_fields(self):
        for field in ("date", "category", "amount", "type"):
            data = self.valid_data()
            del data[field]
            with self.subTest(missing=field):
                self.assert_rejected(
                    data,
                    "Please correct the following errors:",
                )

    def test_invalid_input_is_preserved(self):
        data = self.valid_data(
            date="2026-02-30",
            category="Utilities",
            amount="abc",
            type="income",
        )
        for endpoint in (
            "/add",
            f"/edit/{self.transaction_id}",
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, data=data)
                self.assertEqual(response.status_code, 400)
                page = response.get_data(as_text=True)
                self.assertIn('value="2026-02-30"', page)
                self.assertIn('value="abc"', page)
                self.assertRegex(
                    page, r'value="Utilities"\s+selected'
                )
                self.assertRegex(
                    page, r'value="income"\s+selected'
                )

    def test_whitespace_is_trimmed(self):
        response = self.client.post(
            "/add",
            data=self.valid_data(
                date=" 2026-11-18 ",
                category=" Utilities ",
                amount=" 12.5 ",
                type=" income ",
            ),
        )
        self.assertEqual(response.status_code, 302)
        row = self.rows()[-1]
        self.assertEqual(row["date"], "2026-11-18")
        self.assertEqual(row["category"], "Utilities")
        self.assertEqual(row["amount"], 12.50)
        self.assertEqual(row["type"], "income")

    def test_amount_normalization(self):
        for entered, expected in (
            ("1", "1.00"),
            ("1.2", "1.20"),
            ("001.25", "1.25"),
            ("0.01", "0.01"),
        ):
            with self.subTest(amount=entered):
                _, cleaned, errors = validate_transaction(
                    self.valid_data(amount=entered)
                )
                self.assertEqual(errors, {})
                self.assertEqual(cleaned["amount"], expected)

    def test_form_pages_load(self):
        for endpoint in (
            "/add",
            f"/edit/{self.transaction_id}",
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200)

    def test_missing_transaction_returns_404(self):
        for method in (self.client.get, self.client.post):
            response = method(
                "/edit/999999", data=self.valid_data()
            )
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()