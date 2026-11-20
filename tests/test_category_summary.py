import re
import unittest
from contextlib import closing

from finance.category_summary import (
    calculate_category_summary,
    read_category_summary,
)
from test_support import AccountTestCase


class CategorySummaryCalculationTests(unittest.TestCase):
    def row(self, transactions=(), budgets=None, categories=("Travel",)):
        rows = calculate_category_summary(
            transactions,
            budgets or {},
            categories,
        )
        return next(
            row for row in rows
            if row["category"] == "Travel"
        )

    def test_expenses_only_and_decimal_arithmetic(self):
        row = self.row(
            [
                {"category": "Travel", "amount": 0.1, "type": "expense"},
                {"category": "Travel", "amount": 0.2, "type": "expense"},
                {"category": "Travel", "amount": 100, "type": "income"},
            ],
            {"Travel": "1.00"},
        )

        self.assertEqual(
            (row["expenses"], row["remaining"]),
            ("0.30", "0.70"),
        )

    def test_budget_without_transactions(self):
        row = self.row(
            budgets={"Travel": "100"},
            categories=(),
        )

        self.assertEqual(
            (row["budget"], row["expenses"], row["remaining"]),
            ("100.00", "0.00", "100.00"),
        )

    def test_unset_budget_has_no_alert(self):
        row = self.row(
            [{"category": "Travel", "amount": 500, "type": "expense"}]
        )

        self.assertIsNone(row["budget"])
        self.assertIsNone(row["remaining"])
        self.assertFalse(row["overspent"])
        self.assertEqual(row["status"], "No budget")

    def test_zero_budget_with_and_without_expenses(self):
        row = self.row(budgets={"Travel": "0"})

        self.assertEqual(row["status"], "At budget")
        self.assertFalse(row["overspent"])

        row = self.row(
            [{"category": "Travel", "amount": "0.01", "type": "expense"}],
            {"Travel": "0"},
        )

        self.assertEqual(row["remaining"], "-0.01")
        self.assertTrue(row["overspent"])

    def test_exact_budget_is_not_overspent(self):
        row = self.row(
            [{"category": "Travel", "amount": 100, "type": "expense"}],
            {"Travel": "100"},
        )

        self.assertEqual(
            (row["remaining"], row["status"]),
            ("0.00", "At budget"),
        )
        self.assertFalse(row["overspent"])

    def test_categories_do_not_offset_each_other(self):
        rows = calculate_category_summary(
            [{"category": "Travel", "amount": 150, "type": "expense"}],
            {"Travel": "100", "Rent": "1000"},
        )

        lookup = {row["category"]: row for row in rows}

        self.assertTrue(lookup["Travel"]["overspent"])
        self.assertEqual(
            lookup["Rent"]["remaining"],
            "1000.00",
        )

    def test_custom_category_without_records(self):
        row = self.row()

        self.assertEqual(row["expenses"], "0.00")
        self.assertIsNone(row["remaining"])


class CategorySummaryWorkflowTests(AccountTestCase):
    def budget(self, category, amount, month="2026-11"):
        response = self.post(
            "/category-budgets",
            {
                "month": month,
                "category": category,
                "amount": amount,
            },
        )

        self.assertEqual(response.status_code, 302)

    def summary(self, month="2026-11", user_id=None):
        with closing(self.connect()) as conn:
            rows = read_category_summary(
                conn,
                self.user_id if user_id is None else user_id,
                month,
            )

            return {
                row["category"]: row
                for row in rows
            }

    def html_row(self, page, category):
        match = re.search(
            rb'<tr data-category="' + category.encode() + rb'">.*?</tr>',
            page.data,
            re.S,
        )

        self.assertIsNotNone(match)
        return match.group()

    def test_user_and_month_isolation(self):
        self.budget("Travel", "100")
        self.insert_transaction("2026-11-18", "Travel", 20)
        self.insert_transaction("2026-12-18", "Travel", 50)

        self.insert_transaction(
            "2026-11-18",
            "PrivateOther",
            999,
            user_id=self.other_id,
        )

        self.insert_transaction(
            "2026-10-31",
            "OctoberOnly",
            40,
        )

        self.budget(
            "PreviousBudgetOnly",
            "80",
            month="2026-10",
        )

        rows = self.summary()

        self.assertNotIn("OctoberOnly", rows)
        self.assertNotIn("PreviousBudgetOnly", rows)
        self.assertNotIn("PrivateOther", rows)

        self.assertEqual(
            rows["Travel"]["expenses"],
            "20.00",
        )
        self.assertEqual(
            self.summary("2026-12")["Travel"]["expenses"],
            "50.00",
        )

    def test_no_category_budget_inheritance(self):
        response = self.post(
            "/categories",
            {"name": "Travel"},
        )
        self.assertEqual(response.status_code, 201)

        self.budget("Travel", "100")

        self.assertIsNone(
            self.summary("2026-12")["Travel"]["budget"]
        )

    def test_category_budgets_can_exceed_overall_budget(self):
        self.write_budget("2026-11", "1000")
        self.budget("Travel", "800")
        self.budget("Rent", "700")

        rows = self.summary()

        self.assertEqual(
            (rows["Travel"]["budget"], rows["Rent"]["budget"]),
            ("800.00", "700.00"),
        )
        self.assertEqual(
            self.read_budget(),
            "1000.00",
        )

    def test_category_alert_without_overall_alert(self):
        self.write_budget("2026-11", "1000")
        self.budget("Travel", "100")
        self.insert_transaction("2026-11-18", "Travel", 150)

        page = self.client.get("/?month=2026-11")

        self.assertIn(
            b"Category overspending alert: Travel",
            page.data,
        )
        self.assertNotIn(
            b"Overspending alert: expenses exceed the monthly budget.",
            page.data,
        )
        self.assertIn(
            b"CNY -50.00",
            self.html_row(page, "Travel"),
        )

    def test_overall_alert_without_category_alert(self):
        self.write_budget("2026-11", "100")
        self.budget("Travel", "300")
        self.insert_transaction("2026-11-18", "Travel", 150)

        page = self.client.get("/?month=2026-11")

        self.assertIn(
            b"Overspending alert: expenses exceed the monthly budget.",
            page.data,
        )
        self.assertNotIn(
            b"Category overspending alert:",
            page.data,
        )
        self.assertIn(
            b"Within budget",
            self.html_row(page, "Travel"),
        )

    def test_summary_visible_on_both_pages(self):
        self.budget("Travel", "50")
        self.insert_transaction("2026-11-18", "Travel", 70)

        for endpoint in (
            "/?month=2026-11",
            "/category-budgets?month=2026-11",
        ):
            with self.subTest(endpoint=endpoint):
                page = self.client.get(endpoint)

                self.assertEqual(page.status_code, 200)
                self.assertIn(
                    b"CNY -20.00",
                    self.html_row(page, "Travel"),
                )
                self.assertIn(
                    b"Category overspending alert: Travel",
                    page.data,
                )

    def test_income_does_not_offset_expenses(self):
        self.budget("Travel", "100")
        self.insert_transaction("2026-11-18", "Travel", 150)
        self.insert_transaction(
            "2026-11-18",
            "Travel",
            1000,
            kind="income",
        )

        self.assertEqual(
            self.summary()["Travel"]["remaining"],
            "-50.00",
        )

    def test_transaction_add_edit_delete_refreshes_summary(self):
        self.budget("Travel", "100")

        response = self.post(
            "/add",
            {
                "date": "2026-11-18",
                "category": "Travel",
                "amount": "120",
                "type": "expense",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.summary()["Travel"]["overspent"]
        )

        with closing(self.connect()) as conn:
            transaction_id = conn.execute(
                """SELECT id FROM account_transactions
                   WHERE user_id = ?""",
                (self.user_id,),
            ).fetchone()[0]

        response = self.post(
            f"/edit/{transaction_id}",
            {
                "date": "2026-11-18",
                "category": "Travel",
                "amount": "20",
                "type": "expense",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.summary()["Travel"]["remaining"],
            "80.00",
        )

        response = self.post(
            f"/delete/{transaction_id}"
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.summary()["Travel"]["expenses"],
            "0.00",
        )

    def test_editing_transaction_month_moves_expenses(self):
        response = self.post(
            "/categories",
            {"name": "Travel"},
        )
        self.assertEqual(response.status_code, 201)

        transaction_id = self.insert_transaction(
            "2026-11-18",
            "Travel",
            30,
        )

        response = self.post(
            f"/edit/{transaction_id}",
            {
                "date": "2026-12-18",
                "category": "Travel",
                "amount": "30",
                "type": "expense",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.summary()["Travel"]["expenses"],
            "0.00",
        )
        self.assertEqual(
            self.summary("2026-12")["Travel"]["expenses"],
            "30.00",
        )

    def test_invalid_month_shows_no_summary(self):
        for endpoint in (
            "/?month=invalid",
            "/category-budgets?month=invalid",
        ):
            page = self.client.get(endpoint)

            self.assertEqual(page.status_code, 400)
            self.assertNotIn(
                b'id="category-summary-heading"',
                page.data,
            )

    def test_anonymous_and_admin_cannot_view_private_summary(self):
        self.budget("PrivateTravel", "123")
        anonymous = self.client.application.test_client()

        for endpoint in ("/", "/category-budgets"):
            self.assertEqual(
                anonymous.get(endpoint).status_code,
                302,
            )

        self.login(
            "test_admin",
            "AdminPassword123!",
        )

        for endpoint in ("/", "/category-budgets"):
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                response.location.endswith("/admin")
            )

    def test_custom_names_are_escaped_and_private(self):
        response = self.post(
            "/categories",
            {"name": "<b>PrivateTravel</b>"},
        )

        self.assertEqual(response.status_code, 201)

        page = self.client.get("/?month=2026-11")

        self.assertIn(
            b"&lt;b&gt;PrivateTravel&lt;/b&gt;",
            page.data,
        )
        self.assertNotIn(
            b"<b>PrivateTravel</b>",
            page.data,
        )

        self.login(
            "other_owner",
            "OtherPassword123!",
        )

        self.assertNotIn(
            b"PrivateTravel",
            self.client.get("/?month=2026-11").data,
        )

    def test_reading_summary_does_not_create_budget_records(self):
        self.client.get("/?month=2026-11")
        self.client.get("/category-budgets?month=2026-12")

        with closing(self.connect()) as conn:
            for table in (
                "account_monthly_budgets",
                "account_budget_defaults",
                "account_category_budgets",
            ):
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                self.assertEqual(count, 0)