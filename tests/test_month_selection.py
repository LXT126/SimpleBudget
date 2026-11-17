from test_support import AccountTestCase
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

import app as application


class MonthSelectionTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        for day, category, amount, kind in (
            ("2026-10-31", "OctoberOnly", 10, "expense"),
            ("2026-11-01", "NovemberStart", 20, "expense"),
            ("2026-11-30", "NovemberEnd", 30, "income"),
            ("2026-12-01", "DecemberOnly", 40, "expense"),
            ("2025-11-15", "PreviousYear", 50, "expense"),
        ):
            self.insert_transaction(day, category, amount, kind)


    def test_month_boundaries(self):
        response = self.client.get("/?month=2026-11")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("NovemberStart", text)
        self.assertIn("NovemberEnd", text)
        self.assertNotIn("OctoberOnly", text)
        self.assertNotIn("DecemberOnly", text)

    def test_different_year(self):
        response = self.client.get("/?month=2025-11")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("PreviousYear", text)
        self.assertNotIn("NovemberStart", text)
        self.assertNotIn("NovemberEnd", text)

    def test_empty_month(self):
        response = self.client.get("/?month=2024-02")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No transactions for 2024-02.", text)
        self.assertNotIn("NovemberStart", text)

    def test_selected_month_retained(self):
        response = self.client.get("/?month=2026-11")
        self.assertIn(
            'value="2026-11"',
            response.get_data(as_text=True)
        )

    def test_default_current_month(self):
        today = date(2026, 11, 18)
        self.insert_transaction(today.isoformat(), "CurrentMonthRecord", 15)

        response = self.client.get("/")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("CurrentMonthRecord", text)
        self.assertIn(
            f'value="{today.strftime("%Y-%m")}"',
            text
        )

    def test_invalid_months(self):
        invalid_values = [
            "2026-13", "2026-00", "0000-01",
            "2026-1", "", "hello",
            "2026-11' OR 1=1--"
        ]

        for value in invalid_values:
            with self.subTest(month=value):
                response = self.client.get(
                    "/", query_string={"month": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(
                    "Invalid month.",
                    response.get_data(as_text=True)
                )

    def test_requests_do_not_change_data(self):
        with closing(self.connect()) as conn, conn:
            before = [
                tuple(row)
                for row in conn.execute(
                    "SELECT * FROM account_transactions ORDER BY id"
                )
            ]

        self.client.get("/?month=2026-11")
        self.client.get("/?month=2026-13")

        with closing(self.connect()) as conn, conn:
            after = [
                tuple(row)
                for row in conn.execute(
                    "SELECT * FROM account_transactions ORDER BY id"
                )
            ]

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()