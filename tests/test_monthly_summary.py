from test_support import AccountTestCase
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as application


class MonthlySummaryTests(AccountTestCase):
    def setUp(self):
        super().setUp()


    def add_transaction(self, amount, kind="expense", day="2026-11-15"):
        return self.insert_transaction(day, "Food", amount, kind)

    def set_budget(self, amount, month="2026-11"):
        self.write_budget(month, amount)

    def page(self, month="2026-11"):
        response = self.client.get("/", query_string={"month": month})
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_expenses_exclude_income(self):
        self.add_transaction("12.50")
        self.add_transaction("7.25")
        self.add_transaction("1000.00", kind="income")
        self.set_budget("100")

        page = self.page()
        self.assertIn("Total expenses: CNY 19.75", page)
        self.assertIn("Remaining budget: CNY 80.25", page)
        self.assertNotIn("Overspending alert:", page)

    def test_month_and_year_isolation(self):
        self.add_transaction("10", day="2026-11-01")
        self.add_transaction("20", day="2026-11-30")
        self.add_transaction("40", day="2026-10-31")
        self.add_transaction("50", day="2026-12-01")
        self.add_transaction("60", day="2025-11-15")

        for month, expected in (
            ("2026-11", "30.00"),
            ("2026-12", "50.00"),
            ("2025-11", "60.00"),
        ):
            with self.subTest(month=month):
                self.assertIn(
                    f"Total expenses: CNY {expected}", self.page(month)
                )

    def test_empty_month(self):
        self.set_budget("100")

        page = self.page()
        self.assertIn("Total expenses: CNY 0.00", page)
        self.assertIn("Remaining budget: CNY 100.00", page)
        self.assertNotIn("Overspending alert:", page)

    def test_unset_budget(self):
        self.add_transaction("25")

        page = self.page()
        self.assertIn("Total expenses: CNY 25.00", page)
        self.assertIn("No budget set for this month.", page)
        self.assertNotIn("Remaining budget:", page)
        self.assertNotIn("Overspending alert:", page)

    def test_zero_budget(self):
        self.set_budget("0")

        page = self.page()
        self.assertIn("Remaining budget: CNY 0.00", page)
        self.assertNotIn("Overspending alert:", page)

        self.add_transaction("0.01")
        page = self.page()
        self.assertIn("Remaining budget: CNY -0.01", page)
        self.assertIn("Overspending alert:", page)

    def test_exact_budget_is_not_overspent(self):
        self.set_budget("100")
        self.add_transaction("100")

        page = self.page()
        self.assertIn("Remaining budget: CNY 0.00", page)
        self.assertNotIn("Overspending alert:", page)

    def test_overspending_keeps_negative_remaining(self):
        self.set_budget("100")
        self.add_transaction("120.50")

        page = self.page()
        self.assertIn("Total expenses: CNY 120.50", page)
        self.assertIn("Remaining budget: CNY -20.50", page)
        self.assertIn("Overspending alert:", page)

    def test_decimal_amounts(self):
        self.set_budget("1")
        self.add_transaction("0.10")
        self.add_transaction("0.20")

        page = self.page()
        self.assertIn("Total expenses: CNY 0.30", page)
        self.assertIn("Remaining budget: CNY 0.70", page)

    def test_summary_updates_after_transaction_changes(self):
        self.set_budget("100")
        response = self.post(
            "/add",
            data={
                "date": "2026-11-15",
                "category": "Food",
                "amount": "120",
                "type": "expense",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Remaining budget: CNY -20.00", self.page())

        with closing(self.connect()) as conn:
            transaction_id = conn.execute(
                "SELECT id FROM account_transactions"
            ).fetchone()["id"]

        response = self.post(
            f"/edit/{transaction_id}",
            data={
                "date": "2026-11-15",
                "category": "Food",
                "amount": "40",
                "type": "expense",
            },
        )
        self.assertEqual(response.status_code, 302)
        page = self.page()
        self.assertIn("Total expenses: CNY 40.00", page)
        self.assertIn("Remaining budget: CNY 60.00", page)
        self.assertNotIn("Overspending alert:", page)

        response = self.post(f"/delete/{transaction_id}")
        self.assertEqual(response.status_code, 302)
        page = self.page()
        self.assertIn("Total expenses: CNY 0.00", page)
        self.assertIn("Remaining budget: CNY 100.00", page)

    def test_summary_updates_after_budget_change(self):
        self.add_transaction("120")
        self.set_budget("100")
        self.assertIn("Overspending alert:", self.page())

        response = self.post(
            "/", data={"month": "2026-11", "budget": "150"}
        )
        self.assertEqual(response.status_code, 302)
        page = self.page()
        self.assertIn("Remaining budget: CNY 30.00", page)
        self.assertNotIn("Overspending alert:", page)


if __name__ == "__main__":
    unittest.main()