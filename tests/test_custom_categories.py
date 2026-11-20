from contextlib import closing

from test_support import AccountTestCase


class CustomCategoryTests(AccountTestCase):
    def add_category(self, name, **extra):
        return self.post(
            "/categories",
            dict(name=name, **extra),
        )

    def names(self):
        with closing(self.connect()) as conn:
            return [
                tuple(row)
                for row in conn.execute(
                    """SELECT user_id, name
                       FROM account_categories
                       ORDER BY user_id, name"""
                )
            ]

    def test_add_category_persists_without_budget(self):
        response = self.add_category("Travel")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json(),
            {"name": "Travel"},
        )
        self.assertEqual(
            self.names(),
            [(self.user_id, "Travel")],
        )

        self.assertIn(
            b'value="Travel"',
            self.client.get("/add").data,
        )

        transaction_id = self.insert_transaction(
            "2026-11-18",
            "Travel",
            10,
        )

        self.assertIn(
            b'value="Travel"',
            self.client.get(
                f"/edit/{transaction_id}"
            ).data,
        )

        self.assertIn(
            b"Travel",
            self.client.get(
                "/category-budgets?month=2026-12"
            ).data,
        )

        with closing(self.connect()) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM account_category_budgets"
            ).fetchone()[0]

            self.assertEqual(count, 0)

    def test_trim_name(self):
        self.add_category("  Travel  ")

        self.assertEqual(
            self.names(),
            [(self.user_id, "Travel")],
        )

    def test_invalid_names(self):
        for name in ("", "   ", "x" * 81):
            with self.subTest(name=name):
                self.assertEqual(
                    self.add_category(name).status_code,
                    400,
                )

        self.assertEqual(self.names(), [])

    def test_duplicate_name_rejected(self):
        self.add_category("Travel")

        response = self.add_category("travel")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.names()), 1)

    def test_default_category_duplicate_rejected(self):
        response = self.add_category("groceries")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.names(), [])

    def test_private_categories_and_forged_owner(self):
        self.add_category(
            "PrivateTravel",
            user_id=self.other_id,
        )

        self.assertEqual(
            self.names(),
            [(self.user_id, "PrivateTravel")],
        )

        self.login(
            "other_owner",
            "OtherPassword123!",
        )

        response = self.client.get("/category-budgets")

        self.assertNotIn(
            b"PrivateTravel",
            response.data,
        )

        self.assertEqual(
            self.add_category("PrivateTravel").status_code,
            201,
        )
        self.assertEqual(len(self.names()), 2)

    def test_csrf_required(self):
        response = self.client.post(
            "/categories",
            data={"name": "Travel"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.names(), [])

    def test_anonymous_and_admin_cannot_create(self):
        anonymous = self.client.application.test_client()

        response = self.post(
            "/categories",
            {"name": "Travel"},
            client=anonymous,
        )

        self.assertEqual(response.status_code, 302)

        self.login(
            "test_admin",
            "AdminPassword123!",
        )

        response = self.add_category("Travel")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.names(), [])

    def test_existing_private_categories_are_available(self):
        self.insert_transaction(
            "2026-11-18",
            "LegacyCategory",
            10,
        )

        response = self.client.get("/category-budgets")

        self.assertIn(
            b"LegacyCategory",
            response.data,
        )

        self.assertEqual(
            self.add_category("LegacyCategory").status_code,
            400,
        )

    def test_names_are_html_escaped(self):
        self.add_category("<script>alert(1)</script>")

        page = self.client.get(
            "/category-budgets"
        ).data

        self.assertIn(
            b"&lt;script&gt;alert(1)&lt;/script&gt;",
            page,
        )
        self.assertNotIn(
            b"<script>alert(1)</script>",
            page,
        )