"""B5: month/category ownership, validation and protected saves."""

from contextlib import closing

from test_support import AccountTestCase


class CategoryBudgetTests(AccountTestCase):
    def save(
        self,
        month="2026-11",
        category="Groceries",
        amount="250.50",
        **extra,
    ):
        return self.post(
            "/category-budgets",
            dict(
                month=month,
                category=category,
                amount=amount,
                **extra,
            ),
        )

    def rows(self):
        with closing(self.connect()) as conn:
            return [
                tuple(row)
                for row in conn.execute(
                    """SELECT user_id, month, category, amount
                       FROM account_category_budgets
                       ORDER BY user_id, month, category"""
                )
            ]

    def test_save_and_update_without_duplicate(self):
        self.assertEqual(self.save().status_code, 302)
        self.assertEqual(
            self.save(amount="300").status_code,
            302,
        )

        self.assertEqual(
            self.rows(),
            [
                (
                    self.user_id,
                    "2026-11",
                    "Groceries",
                    "300.00",
                )
            ],
        )

    def test_month_and_category_are_independent(self):
        self.save()
        self.save(month="2026-12", amount="400")
        self.save(category="Rent", amount="800")

        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.rows()[0][3], "250.50")

    def test_zero_is_set_and_unset_is_distinct(self):
        self.save(amount="0")

        response = self.client.get(
            "/category-budgets?month=2026-11"
        )

        self.assertIn(b"CNY 0.00", response.data)
        self.assertIn(b"Not set", response.data)

    def test_no_inheritance(self):
        self.save()

        response = self.client.get(
            "/category-budgets?month=2026-12"
        )

        self.assertNotIn(b"CNY 250.50", response.data)
        self.assertIn(b"Not set", response.data)
        self.assertEqual(len(self.rows()), 1)

    def test_invalid_amounts_do_not_overwrite(self):
        self.save()
        original = self.rows()

        for amount in (
            "",
            "-1",
            "1.234",
            "NaN",
            "Infinity",
            "1e2",
            "abc",
        ):
            with self.subTest(amount=amount):
                response = self.save(amount=amount)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.rows(), original)

    def test_invalid_months_do_not_write(self):
        for month in (
            "",
            "2026-13",
            "0000-11",
            "2026-1",
            "invalid",
        ):
            with self.subTest(month=month):
                response = self.save(month=month)

                self.assertEqual(response.status_code, 400)

        self.assertEqual(self.rows(), [])

    def test_empty_category_rejected(self):
        response = self.save(category="  ")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows(), [])

    def test_trim_category_and_normalize_amount(self):
        self.save(
            category="  Travel  ",
            amount=" 0012.5 ",
        )

        self.assertEqual(
            self.rows(),
            [
                (
                    self.user_id,
                    "2026-11",
                    "Travel",
                    "12.50",
                )
            ],
        )

    def test_invalid_input_preserved(self):
        response = self.save(
            category="Travel",
            amount="bad-amount",
        )

        self.assertIn(b'value="Travel"', response.data)
        self.assertIn(b'value="bad-amount"', response.data)
        self.assertIn(b'role="alert"', response.data)

    def test_other_users_cannot_read_or_overwrite(self):
        self.save(
            category="PrivateCategory",
            amount="321",
        )

        self.login(
            "other_owner",
            "OtherPassword123!",
        )

        response = self.client.get(
            "/category-budgets?month=2026-11"
        )

        self.assertNotIn(
            b"PrivateCategory",
            response.data,
        )

        self.save(
            category="PrivateCategory",
            amount="5",
            user_id=self.user_id,
        )

        self.assertEqual(
            self.rows(),
            [
                (
                    self.user_id,
                    "2026-11",
                    "PrivateCategory",
                    "321.00",
                ),
                (
                    self.other_id,
                    "2026-11",
                    "PrivateCategory",
                    "5.00",
                ),
            ],
        )

    def test_csrf_is_required(self):
        response = self.client.post(
            "/category-budgets",
            data={
                "month": "2026-11",
                "category": "Rent",
                "amount": "1",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows(), [])

    def test_anonymous_and_admin_cannot_save(self):
        anonymous = self.client.application.test_client()

        self.assertEqual(
            anonymous.get("/category-budgets").status_code,
            302,
        )

        response = self.post(
            "/category-budgets",
            {
                "month": "2026-11",
                "category": "Rent",
                "amount": "1",
            },
            client=anonymous,
        )

        self.assertEqual(response.status_code, 302)

        self.login(
            "test_admin",
            "AdminPassword123!",
        )

        response = self.save()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/admin")
        )
        self.assertEqual(self.rows(), [])

    def test_monthly_budget_unchanged(self):
        self.write_budget("2026-11", "1000")
        self.save(amount="2000")

        self.assertEqual(
            self.read_budget(),
            "1000.00",
        )
        self.assertEqual(
            self.read_budget("2026-12"),
            "1000.00",
        )

    def test_database_failure_preserves_saved_budget(self):
        self.save()

        with closing(self.connect()) as conn, conn:
            conn.execute(
                """CREATE TRIGGER reject_category_update
                   BEFORE UPDATE ON account_category_budgets
                   BEGIN
                       SELECT RAISE(ABORT, 'forced failure');
                   END"""
            )

        response = self.save(amount="500")

        self.assertEqual(response.status_code, 503)
        self.assertIn(
            b"could not be saved",
            response.data,
        )
        self.assertEqual(
            self.rows()[0][3],
            "250.50",
        )