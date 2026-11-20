import re
from contextlib import closing

from finance.category_summary import read_category_summary
from test_support import AccountTestCase


class RecategorisationTests(AccountTestCase):
    def setUp(self):
        super().setUp()

        self.transaction_id = self.insert_transaction(
            "2026-11-18",
            "Groceries",
            "125.50",
        )
        self.endpoint = (
            f"/recategorise/{self.transaction_id}"
        )

    def record(self, transaction_id=None):
        with closing(self.connect()) as conn:
            row = conn.execute(
                """SELECT * FROM account_transactions
                   WHERE id = ?""",
                (
                    self.transaction_id
                    if transaction_id is None
                    else transaction_id,
                ),
            ).fetchone()

            return None if row is None else dict(row)

    def save(self, category="Rent", **extra):
        return self.post(
            self.endpoint,
            dict(
                category=category,
                month="2026-11",
                **extra,
            ),
        )

    def summaries(self):
        with closing(self.connect()) as conn:
            return {
                row["category"]: row
                for row in read_category_summary(
                    conn,
                    self.user_id,
                    "2026-11",
                )
            }

    def test_form_selects_current_category(self):
        page = self.client.get(
            self.endpoint + "?month=2026-11"
        )

        self.assertEqual(page.status_code, 200)
        self.assertRegex(
            page.get_data(as_text=True),
            r'<option value="Groceries"\s+selected',
        )
        self.assertIn(
            b'name="csrf_token"',
            page.data,
        )

    def test_change_preserves_other_fields_and_row_count(self):
        before = self.record()

        self.assertEqual(
            self.save().status_code,
            302,
        )

        after = self.record()

        self.assertEqual(
            after,
            dict(before, category="Rent"),
        )

        with closing(self.connect()) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM account_transactions"
                ).fetchone()[0],
                1,
            )

    def test_save_and_cancel_keep_selected_month(self):
        page = self.client.get(
            self.endpoint + "?month=2026-10"
        )

        self.assertIn(
            b'name="month" value="2026-10"',
            page.data,
        )
        self.assertIn(
            b'/?month=2026-10#transactions-heading',
            page.data,
        )

        response = self.post(
            self.endpoint,
            {
                "category": "Rent",
                "month": "2026-10",
            },
        )

        self.assertTrue(
            response.location.endswith(
                "/?month=2026-10#transactions-heading"
            )
        )

    def test_opening_form_does_not_change_transaction(self):
        before = self.record()

        self.client.get(self.endpoint)

        self.assertEqual(
            self.record(),
            before,
        )

    def test_own_custom_category_is_available(self):
        response = self.post(
            "/categories",
            {"name": "Travel"},
        )

        self.assertEqual(response.status_code, 201)

        self.assertIn(
            b'value="Travel"',
            self.client.get(self.endpoint).data,
        )

        self.assertEqual(
            self.save("Travel").status_code,
            302,
        )
        self.assertEqual(
            self.record()["category"],
            "Travel",
        )

    def test_other_users_custom_category_is_unavailable(self):
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """INSERT INTO account_categories(user_id, name)
                   VALUES (?, ?)""",
                (self.other_id, "PrivateOther"),
            )

        self.assertNotIn(
            b"PrivateOther",
            self.client.get(self.endpoint).data,
        )

        before = self.record()

        self.assertEqual(
            self.save("PrivateOther").status_code,
            400,
        )
        self.assertEqual(
            self.record(),
            before,
        )

    def test_empty_and_unknown_category_preserve_record(self):
        before = self.record()

        for category in ("", "  ", "UnavailableCategory"):
            with self.subTest(category=category):
                page = self.save(category)

                self.assertEqual(page.status_code, 400)
                self.assertIn(
                    b'role="alert"',
                    page.data,
                )
                self.assertEqual(
                    self.record(),
                    before,
                )

    def test_missing_and_invalid_csrf_rejected(self):
        before = self.record()

        for fields in (
            {"category": "Rent"},
            {
                "category": "Rent",
                "csrf_token": "wrong",
            },
        ):
            self.assertEqual(
                self.client.post(
                    self.endpoint,
                    data=fields,
                ).status_code,
                400,
            )

        self.assertEqual(
            self.record(),
            before,
        )

    def test_other_users_transaction_returns_404(self):
        other_id = self.insert_transaction(
            "2026-11-18",
            "Groceries",
            5,
            user_id=self.other_id,
        )

        before = self.record(other_id)

        self.assertEqual(
            self.client.get(
                f"/recategorise/{other_id}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.post(
                f"/recategorise/{other_id}",
                {"category": "Rent"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.record(other_id),
            before,
        )

    def test_missing_transaction_returns_404(self):
        self.assertEqual(
            self.client.get(
                "/recategorise/999999"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.post(
                "/recategorise/999999",
                {"category": "Rent"},
            ).status_code,
            404,
        )

    def test_anonymous_user_cannot_read_or_save(self):
        anonymous = self.client.application.test_client()
        before = self.record()

        self.assertEqual(
            anonymous.get(self.endpoint).status_code,
            302,
        )
        self.assertEqual(
            self.post(
                self.endpoint,
                {"category": "Rent"},
                client=anonymous,
            ).status_code,
            302,
        )
        self.assertEqual(
            self.record(),
            before,
        )

    def test_admin_cannot_read_or_save(self):
        self.login(
            "test_admin",
            "AdminPassword123!",
        )

        before = self.record()

        for response in (
            self.client.get(self.endpoint),
            self.save(),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                response.location.endswith("/admin")
            )

        self.assertEqual(
            self.record(),
            before,
        )

    def test_same_category_does_not_duplicate_transaction(self):
        before = self.record()

        self.assertEqual(
            self.save("Groceries").status_code,
            302,
        )
        self.assertEqual(
            self.record(),
            before,
        )

        with closing(self.connect()) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM account_transactions"
                ).fetchone()[0],
                1,
            )

    def test_database_failure_rolls_back(self):
        before = self.record()

        with closing(self.connect()) as conn, conn:
            conn.execute(
                """CREATE TRIGGER reject_recategorise
                   BEFORE UPDATE OF category ON account_transactions
                   BEGIN
                       SELECT RAISE(ABORT, 'forced failure');
                   END"""
            )

        page = self.save()

        self.assertEqual(page.status_code, 503)
        self.assertIn(
            b"Category could not be updated",
            page.data,
        )
        self.assertIn(
            b'value="Rent" selected',
            page.data,
        )
        self.assertEqual(
            self.record(),
            before,
        )

    def test_forged_fields_are_ignored(self):
        before = self.record()

        response = self.save(
            date="2025-01-01",
            amount="999",
            type="income",
            user_id=self.other_id,
            id=999999,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.record(),
            dict(before, category="Rent"),
        )

    def test_expense_summaries_and_alerts_move_between_categories(self):
        self.write_budget("2026-11", "1000")

        for category, amount in (
            ("Groceries", "100"),
            ("Rent", "50"),
        ):
            response = self.post(
                "/category-budgets",
                {
                    "month": "2026-11",
                    "category": category,
                    "amount": amount,
                },
            )

            self.assertEqual(response.status_code, 302)

        before = self.summaries()

        self.assertTrue(
            before["Groceries"]["overspent"]
        )

        self.assertEqual(
            self.save().status_code,
            302,
        )

        after = self.summaries()

        self.assertEqual(
            after["Groceries"]["expenses"],
            "0.00",
        )
        self.assertFalse(
            after["Groceries"]["overspent"]
        )
        self.assertEqual(
            after["Rent"]["remaining"],
            "-75.50",
        )
        self.assertTrue(
            after["Rent"]["overspent"]
        )

        self.assertEqual(
            sum(float(row["expenses"]) for row in before.values()),
            sum(float(row["expenses"]) for row in after.values()),
        )
        self.assertEqual(
            self.read_budget(),
            "1000.00",
        )

    def test_income_recategorisation_does_not_add_expenses(self):
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """UPDATE account_transactions
                   SET type = 'income'
                   WHERE id = ?""",
                (self.transaction_id,),
            )

        self.assertEqual(
            self.save("Salary").status_code,
            302,
        )

        rows = self.summaries()

        self.assertEqual(
            rows["Groceries"]["expenses"],
            "0.00",
        )
        self.assertEqual(
            rows["Salary"]["expenses"],
            "0.00",
        )
        self.assertEqual(
            self.record()["type"],
            "income",
        )

    def test_invalid_month_rejected_without_changes(self):
        before = self.record()

        self.assertEqual(
            self.client.get(
                self.endpoint + "?month=invalid"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post(
                self.endpoint,
                {
                    "category": "Rent",
                    "month": "invalid",
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.record(),
            before,
        )