import unittest
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from flask import template_rendered

import app as application
from finance.account_storage import add_user_category
from test_month_selection import TransactionsParser
from test_support import AccountTestCase


class CategoryFilterTests(AccountTestCase):
    def setUp(self):
        super().setUp()

        self.grocery_id = self.insert_transaction(
            "2026-11-01", "Groceries", 25
        )
        self.insert_transaction(
            "2026-11-30", "Rent", 100
        )
        self.insert_transaction(
            "2026-11-15", "Salary", 500, "income"
        )
        self.insert_transaction(
            "2026-10-31", "Groceries", 40
        )
        self.insert_transaction(
            "2025-11-01", "Groceries", 60
        )
        self.insert_transaction(
            "2026-11-01",
            "Groceries",
            999,
            user_id=self.other_id,
        )
        self.write_budget("2026-11", "1000")

        self.contexts = []

        def capture(sender, template, context, **extra):
            if template.name == "index.html":
                self.contexts.append(context.copy())

        template_rendered.connect(
            capture, application.app, weak=False
        )
        self.addCleanup(
            template_rendered.disconnect,
            capture,
            application.app,
        )

    def page(self, category="", month="2026-11"):
        response = self.client.get(
            "/",
            query_string={
                "month": month,
                "category": category,
            },
        )
        self.assertEqual(response.status_code, 200)

        parser = TransactionsParser()
        parser.feed(response.get_data(as_text=True))
        return response, parser

    def test_default_all_categories(self):
        response = self.client.get("/?month=2026-11")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            len(self.contexts[-1]["transactions"]), 3
        )
        self.assertEqual(
            self.contexts[-1]["selected_filter"], ""
        )

    def test_month_and_category_together(self):
        _, page = self.page("Groceries")

        self.assertEqual(
            page.records,
            [
                (
                    "2026-11-01",
                    "Groceries",
                    "25.00",
                    "expense",
                )
            ],
        )

    def test_other_month_and_year(self):
        _, page = self.page("Groceries", "2025-11")

        self.assertEqual(
            page.records,
            [
                (
                    "2025-11-01",
                    "Groceries",
                    "60.00",
                    "expense",
                )
            ],
        )

    def test_income_can_be_filtered(self):
        _, page = self.page("Salary")

        self.assertEqual(
            page.records,
            [
                (
                    "2026-11-15",
                    "Salary",
                    "500.00",
                    "income",
                )
            ],
        )

    def test_full_month_summary_unchanged(self):
        self.page()
        original = self.contexts[-1]

        self.page("Groceries")
        filtered = self.contexts[-1]

        self.assertEqual(
            filtered["summary"], original["summary"]
        )
        self.assertEqual(
            filtered["monthly_budget"], "1000.00"
        )
        self.assertEqual(
            filtered["category_rows"],
            original["category_rows"],
        )
        self.assertEqual(
            len(filtered["transactions"]), 1
        )

    def test_no_matching_transactions(self):
        response, page = self.page("Utilities")

        self.assertEqual(page.records, [])
        self.assertIn(
            "No transactions for 2026-11 in Utilities.",
            response.get_data(as_text=True),
        )

    def test_unknown_or_private_filter_rejected(self):
        with closing(self.connect()) as conn:
            add_user_category(
                conn, self.other_id, "PrivateOther"
            )

        for category in (
            "Unknown",
            "PrivateOther",
            "' OR 1=1--",
        ):
            with self.subTest(category=category):
                response = self.client.get(
                    "/",
                    query_string={
                        "month": "2026-11",
                        "category": category,
                    },
                )

                self.assertEqual(
                    response.status_code, 400
                )
                self.assertEqual(
                    self.contexts[-1]["transactions"], []
                )

        self.page()
        self.assertNotIn(
            "PrivateOther",
            self.contexts[-1]["filter_categories"],
        )

    def test_own_custom_category_and_selection(self):
        name = "Food & Drinks"

        with closing(self.connect()) as conn:
            add_user_category(conn, self.user_id, name)

        self.insert_transaction(
            "2026-11-03", name, 12.50
        )

        _, page = self.page(name)

        self.assertEqual(
            page.records,
            [
                (
                    "2026-11-03",
                    name,
                    "12.50",
                    "expense",
                )
            ],
        )
        self.assertEqual(
            self.contexts[-1]["selected_filter"], name
        )

    def test_recategorisation_preserves_filter(self):
        response = self.post(
            f"/recategorise/{self.grocery_id}",
            {
                "month": "2026-11",
                "filter_category": "Groceries",
                "category": "Rent",
            },
        )

        self.assertEqual(response.status_code, 302)

        target = urlsplit(response.location)
        self.assertEqual(
            parse_qs(target.query),
            {
                "month": ["2026-11"],
                "category": ["Groceries"],
            },
        )
        self.assertEqual(
            target.fragment, "transactions-heading"
        )

        _, page = self.page("Groceries")
        self.assertEqual(page.records, [])

    def test_failed_recategorisation_retains_filter(self):
        response = self.post(
            f"/recategorise/{self.grocery_id}",
            {
                "month": "2026-11",
                "filter_category": "Groceries",
                "category": "Unknown",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            b'name="filter_category" value="Groceries"',
            response.data,
        )

        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT category
                FROM account_transactions
                WHERE id = ?
                """,
                (self.grocery_id,),
            ).fetchone()

        self.assertEqual(row["category"], "Groceries")

    def test_budget_save_preserves_filter(self):
        response = self.post(
            "/",
            {
                "month": "2026-11",
                "filter_category": "Groceries",
                "budget": "1200",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            parse_qs(urlsplit(response.location).query),
            {
                "month": ["2026-11"],
                "category": ["Groceries"],
            },
        )
        self.assertEqual(self.read_budget(), "1200.00")

    def test_invalid_month_still_rejected(self):
        response = self.client.get(
            "/",
            query_string={
                "month": "2026-13",
                "category": "Groceries",
            },
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()