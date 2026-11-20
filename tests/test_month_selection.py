import unittest
from contextlib import closing
from datetime import date
from html.parser import HTMLParser

from test_support import AccountTestCase


class TransactionsParser(HTMLParser):
    """Read transaction records separately from category choices."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.section_depth = 0
        self.records = []
        self.category_choices = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "section":
            if self.section_depth:
                self.section_depth += 1
            elif (
                attrs.get("aria-labelledby")
                == "transactions-heading"
            ):
                self.section_depth = 1

        if not self.section_depth:
            return

        classes = attrs.get("class", "").split()

        if tag == "button" and "view-transaction" in classes:
            self.records.append(
                (
                    attrs.get("data-date"),
                    attrs.get("data-category"),
                    attrs.get("data-amount"),
                    attrs.get("data-type"),
                )
            )

        if (
            tag == "button"
            and "category-option" in classes
            and attrs.get("name") == "category"
        ):
            self.category_choices.append(attrs.get("value"))

    def handle_endtag(self, tag):
        if tag == "section" and self.section_depth:
            self.section_depth -= 1


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
            self.insert_transaction(
                day, category, amount, kind
            )

    def parse_transactions(self, response):
        parser = TransactionsParser()
        parser.feed(response.get_data(as_text=True))
        parser.close()
        return parser

    def test_month_boundaries(self):
        response = self.client.get("/?month=2026-11")

        self.assertEqual(response.status_code, 200)

        page = self.parse_transactions(response)

        self.assertCountEqual(
            page.records,
            [
                (
                    "2026-11-01",
                    "NovemberStart",
                    "20.00",
                    "expense",
                ),
                (
                    "2026-11-30",
                    "NovemberEnd",
                    "30.00",
                    "income",
                ),
            ],
        )

        # Historical categories may remain available as choices.
        # Their transactions must not appear in this month's list.
        self.assertIn(
            "OctoberOnly", page.category_choices
        )
        self.assertIn(
            "DecemberOnly", page.category_choices
        )

    def test_different_year(self):
        response = self.client.get("/?month=2025-11")

        self.assertEqual(response.status_code, 200)

        page = self.parse_transactions(response)

        self.assertEqual(
            page.records,
            [
                (
                    "2025-11-15",
                    "PreviousYear",
                    "50.00",
                    "expense",
                )
            ],
        )

    def test_empty_month(self):
        response = self.client.get("/?month=2024-02")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "No transactions for 2024-02.", text
        )

        page = self.parse_transactions(response)
        self.assertEqual(page.records, [])

    def test_selected_month_retained(self):
        response = self.client.get("/?month=2026-11")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'value="2026-11"',
            response.get_data(as_text=True),
        )

    def test_default_current_month(self):
        today = date.today()

        self.insert_transaction(
            today.isoformat(),
            "CurrentMonthRecord",
            15,
        )

        response = self.client.get("/")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'value="{today.strftime("%Y-%m")}"',
            text,
        )

        page = self.parse_transactions(response)

        self.assertIn(
            (
                today.isoformat(),
                "CurrentMonthRecord",
                "15.00",
                "expense",
            ),
            page.records,
        )

        self.assertTrue(
            all(
                record[0].startswith(
                    today.strftime("%Y-%m") + "-"
                )
                for record in page.records
            )
        )

    def test_invalid_months(self):
        invalid_values = [
            "2026-13",
            "2026-00",
            "0000-01",
            "2026-1",
            "",
            "hello",
            "2026-11' OR 1=1--",
        ]

        for value in invalid_values:
            with self.subTest(month=value):
                response = self.client.get(
                    "/",
                    query_string={"month": value},
                )

                self.assertEqual(
                    response.status_code, 400
                )
                self.assertIn(
                    "Invalid month.",
                    response.get_data(as_text=True),
                )

    def test_requests_do_not_change_data(self):
        with closing(self.connect()) as conn:
            before = [
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM account_transactions
                    ORDER BY id
                    """
                )
            ]

        self.client.get("/?month=2026-11")
        self.client.get("/?month=2026-13")

        with closing(self.connect()) as conn:
            after = [
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM account_transactions
                    ORDER BY id
                    """
                )
            ]

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()