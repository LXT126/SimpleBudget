from test_support import AccountTestCase
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as application


class MonthlyBudgetTests(AccountTestCase):
    def setUp(self):
        super().setUp()


    def save(self, month="2026-11", amount="1200.50"):
        return self.post(
            "/", data={"month": month, "budget": amount}
        )

    def read(self, month="2026-11"):
        with closing(self.connect()) as conn:
            result = application.read_budget(conn, self.user_id, month)
        return None if result is None else format(result, ".2f")

    def test_save_and_display(self):
        response = self.save()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(
            "/?month=2026-11"
        ))
        self.assertEqual(self.read(), "1200.50")
        page = self.client.get("/?month=2026-11")
        self.assertIn(b"Current budget: CNY 1200.50", page.data)

    def test_update_existing_budget(self):
        self.save(amount="100")
        self.save(amount="250.75")
        self.assertEqual(self.read(), "250.75")
        with closing(self.connect()) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM account_monthly_budgets"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_month_and_year_isolation(self):
        self.save("2026-11", "100")
        self.save("2026-12", "200")
        self.save("2025-11", "300")
        self.assertEqual(self.read("2026-11"), "100.00")
        self.assertEqual(self.read("2026-12"), "200.00")
        self.assertEqual(self.read("2025-11"), "300.00")

    def test_unset_and_zero_are_different(self):
        page = self.client.get("/?month=2026-11")
        self.assertIn(b"No budget set for this month.", page.data)
        self.assertIsNone(self.read())
        self.save(amount="0")
        self.assertEqual(self.read(), "0.00")
        page = self.client.get("/?month=2026-11")
        self.assertIn(b"Current budget: CNY 0.00", page.data)
        self.assertNotIn(b"No budget set for this month.", page.data)

    def test_invalid_amounts_preserve_budget(self):
        self.save(amount="100")
        for amount in (
            "", "-1", "1.234", "abc", "NaN", "Infinity",
            "1e3", "1,000", "'; DROP TABLE monthly_budgets;--"
        ):
            with self.subTest(amount=amount):
                response = self.save(amount=amount)
                self.assertEqual(response.status_code, 400)
                self.assertIn(
                    b"Enter a non-negative budget", response.data
                )
                self.assertEqual(self.read(), "100.00")

    def test_invalid_months_preserve_budget(self):
        self.save(amount="100")
        for month in ("", "0000-01", "2026-13", "2026-1", "hello"):
            with self.subTest(month=month):
                response = self.save(month, "200")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.read(), "100.00")

    def test_persistence_after_reopening_database(self):
        with closing(self.connect()) as conn:
            application.save_budget(conn, self.user_id, "2026-11", "123.45")
        # A new connection reads the committed value from disk.
        self.assertEqual(self.read(), "123.45")

    def test_failed_save_rolls_back(self):
        self.save(amount="100")
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """CREATE TRIGGER reject_budget_update
                   BEFORE UPDATE ON account_monthly_budgets
                   BEGIN
                       SELECT RAISE(ABORT, 'Simulated save failure');
                   END"""
            )

        response = self.save(amount="999")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Budget could not be saved", response.data)
        self.assertEqual(self.read(), "100.00")


if __name__ == "__main__":
    unittest.main()