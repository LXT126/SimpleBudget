from test_support import AccountTestCase
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from account_storage import init_account_tables, import_legacy_data
import app as application


class BudgetInheritanceTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        self.addCleanup(self.conn.close)

    def set_today(self, year, month):
        self.clock.today.return_value = date(year, month, 18)

    def save(self, month, amount):
        application.save_budget(self.conn, self.user_id, month, amount)

    def read(self, month):
        amount = application.read_budget(self.conn, self.user_id, month)
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
        init_account_tables(self.conn)
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
            self.conn.execute("""CREATE TABLE transactions (
                id INTEGER PRIMARY KEY, date TEXT, category TEXT,
                amount REAL, type TEXT)""")
            self.conn.execute("CREATE TABLE monthly_budgets (month TEXT PRIMARY KEY, amount TEXT NOT NULL)")
            self.conn.execute("CREATE TABLE monthly_budget_defaults (month TEXT PRIMARY KEY, amount TEXT NOT NULL)")
            records = [("2026-11", "1200.00"), ("2027-02", "1500.00")]
            self.conn.executemany("INSERT INTO monthly_budgets VALUES (?, ?)", records)
            self.conn.executemany("INSERT INTO monthly_budget_defaults VALUES (?, ?)", records)
        self.assertTrue(import_legacy_data(self.conn, self.user_id))
        self.assertIsNone(self.read("2026-10"))
        self.assertEqual(self.read("2027-01"), "1200.00")
        self.assertEqual(self.read("2027-03"), "1500.00")
        self.assertFalse(import_legacy_data(self.conn, self.user_id))
        self.set_today(2027, 3)
        self.save("2026-11", "900")
        self.assertEqual(self.read("2026-12"), "1200.00")

    def test_failed_default_save_rolls_back_selected_month(self):
        self.save("2026-11", "1200")

        with self.conn:
            self.conn.execute(
                """CREATE TRIGGER reject_default_update
                   BEFORE UPDATE ON account_budget_defaults
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