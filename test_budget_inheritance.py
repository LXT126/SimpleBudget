import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from monthly_budget import (
    get_monthly_budget,
    init_budget_table,
    save_monthly_budget,
)


class BudgetInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)

        date_patch = patch("monthly_budget.date")
        self.clock = date_patch.start()
        self.addCleanup(date_patch.stop)
        self.set_today(2026, 11)

    def set_today(self, year, month):
        self.clock.today.return_value = date(year, month, 18)

    def save(self, month, amount):
        save_monthly_budget(self.conn, month, amount)

    def read(self, month):
        amount = get_monthly_budget(self.conn, month)
        return None if amount is None else format(amount, ".2f")

    def test_budget_carries_forward_across_years(self):
        self.save("2026-11", "1200.50")

        for month in ("2026-11", "2026-12", "2027-01", "2028-06"):
            with self.subTest(month=month):
                self.assertEqual(self.read(month), "1200.50")

        self.assertIsNone(self.read("2026-10"))

    def test_later_change_preserves_previous_months(self):
        self.save("2026-11", "1200")

        self.set_today(2027, 2)
        self.save("2027-02", "1500")

        self.assertEqual(self.read("2026-11"), "1200.00")
        self.assertEqual(self.read("2026-12"), "1200.00")
        self.assertEqual(self.read("2027-01"), "1200.00")
        self.assertEqual(self.read("2027-02"), "1500.00")
        self.assertEqual(self.read("2027-03"), "1500.00")

    def test_historical_edit_changes_only_selected_month(self):
        self.save("2026-11", "1200")

        self.set_today(2027, 2)
        self.save("2027-02", "1500")
        self.save("2026-12", "1000")

        self.assertEqual(self.read("2026-11"), "1200.00")
        self.assertEqual(self.read("2026-12"), "1000.00")
        self.assertEqual(self.read("2027-01"), "1200.00")
        self.assertEqual(self.read("2027-02"), "1500.00")
        self.assertEqual(self.read("2027-03"), "1500.00")

    def test_editing_original_historical_month_keeps_default(self):
        self.save("2026-11", "1200")

        self.set_today(2027, 2)
        self.save("2026-11", "900")

        self.assertEqual(self.read("2026-11"), "900.00")
        self.assertEqual(self.read("2026-12"), "1200.00")
        self.assertEqual(self.read("2027-03"), "1200.00")

        # Reinitialisation must not overwrite the preserved default.
        init_budget_table(self.conn)
        self.assertEqual(self.read("2027-03"), "1200.00")

    def test_historical_first_budget_does_not_create_default(self):
        self.set_today(2027, 2)
        self.save("2026-12", "800")

        self.assertIsNone(self.read("2026-11"))
        self.assertEqual(self.read("2026-12"), "800.00")
        self.assertIsNone(self.read("2027-01"))
        self.assertIsNone(self.read("2027-03"))

    def test_future_change_preserves_another_scheduled_change(self):
        self.save("2026-11", "1200")
        self.save("2027-02", "1500")
        self.save("2026-12", "1300")

        self.assertEqual(self.read("2026-11"), "1200.00")
        self.assertEqual(self.read("2026-12"), "1300.00")
        self.assertEqual(self.read("2027-01"), "1300.00")
        self.assertEqual(self.read("2027-02"), "1500.00")

    def test_zero_is_inherited_as_a_valid_budget(self):
        self.save("2026-11", "1200")
        self.save("2026-12", "0")

        self.assertEqual(self.read("2026-11"), "1200.00")
        self.assertEqual(self.read("2026-12"), "0.00")
        self.assertEqual(self.read("2027-01"), "0.00")

    def test_existing_database_is_migrated_once(self):
        with self.conn:
            self.conn.execute(
                """CREATE TABLE monthly_budgets (
                       month TEXT PRIMARY KEY,
                       amount TEXT NOT NULL
                   )"""
            )
            self.conn.executemany(
                "INSERT INTO monthly_budgets VALUES (?, ?)",
                [
                    ("2026-11", "1200.00"),
                    ("2027-02", "1500.00"),
                ]
            )

        self.assertIsNone(self.read("2026-10"))
        self.assertEqual(self.read("2027-01"), "1200.00")
        self.assertEqual(self.read("2027-03"), "1500.00")

        self.set_today(2027, 3)
        self.save("2026-11", "900")
        self.assertEqual(self.read("2026-12"), "1200.00")

    def test_failed_default_save_rolls_back_selected_month(self):
        self.save("2026-11", "1200")

        with self.conn:
            self.conn.execute(
                """CREATE TRIGGER reject_default_update
                   BEFORE UPDATE ON monthly_budget_defaults
                   BEGIN
                       SELECT RAISE(ABORT, 'Simulated save failure');
                   END"""
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.save("2026-11", "1500")

        self.assertEqual(self.read("2026-11"), "1200.00")
        self.assertEqual(self.read("2026-12"), "1200.00")


if __name__ == "__main__":
    unittest.main()