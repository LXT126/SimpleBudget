"Authentication, authorisation, CSRF and migration regression tests."
import sqlite3
from contextlib import closing

from werkzeug.security import check_password_hash

import app as application
from account_storage import import_legacy_data
from test_support import AccountTestCase


class AccountSecurityTests(AccountTestCase):
    def snapshot(self):
        with closing(self.connect()) as conn:
            return {
                table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
                for table in (
                    "account_transactions", "account_monthly_budgets",
                    "account_budget_defaults",
                )
            }

    def valid_transaction(self, **changes):
        fields = {"date": "2026-11-18", "category": "Groceries", "amount": "12.50", "type": "expense"}
        fields.update(changes)
        return fields

    def test_anonymous_pages_require_login(self):
        client = application.app.test_client()
        for endpoint in ("/", "/add", "/edit/1", "/admin"):
            with self.subTest(endpoint=endpoint):
                response = client.get(endpoint)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_anonymous_post_with_valid_token_cannot_change_data(self):
        client = application.app.test_client()
        before = self.snapshot()
        for endpoint, data in (
            ("/add", self.valid_transaction()),
            ("/", {"month": "2026-11", "budget": "100"}),
            ("/edit/1", self.valid_transaction()),
            ("/delete/1", {}),
        ):
            with self.subTest(endpoint=endpoint):
                response = self.post(endpoint, data, client=client)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["Location"].endswith("/login"))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_credentials_do_not_log_in(self):
        client = application.app.test_client()
        for username, password in (("test_owner", "wrong-password"), ("missing", "TestPassword123!")):
            response = self.post("/login", {"username": username, "password": password}, client=client)
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"Invalid username or password.", response.data)
            with client.session_transaction() as state:
                self.assertNotIn("user_id", state)

    def test_login_rotates_token_and_logout_removes_access(self):
        client = application.app.test_client()
        old_token = self.token(client)
        self.login(client=client)
        new_token = self.token(client)
        self.assertNotEqual(old_token, new_token)
        before = self.snapshot()
        response = client.post("/add", data={**self.valid_transaction(), "csrf_token": old_token})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.post("/logout", client=client).status_code, 302)
        self.assertEqual(client.get("/").status_code, 302)
        with client.session_transaction() as state:
            self.assertNotIn("user_id", state)

    def test_register_always_creates_regular_user(self):
        client = application.app.test_client()
        response = self.post("/register", {
            "username": "new_member", "password": "NewPassword123!",
            "confirm_password": "NewPassword123!", "role": "admin",
        }, client=client)
        self.assertEqual(response.status_code, 302)
        with closing(self.connect()) as conn:
            user = conn.execute("SELECT * FROM users WHERE username = 'new_member'").fetchone()
        self.assertEqual(user["role"], "user")
        self.assertNotEqual(user["password_hash"], "NewPassword123!")
        self.assertTrue(check_password_hash(user["password_hash"], "NewPassword123!"))
        self.assertTrue(user["registered_at"].endswith("+00:00"))
        self.login("new_member", "NewPassword123!", client=client)
        self.assertEqual(client.get("/admin").status_code, 403)
        self.assertIn(b"No transactions for 2026-11.", client.get("/?month=2026-11").data)

    def test_registration_rejects_invalid_input_and_duplicates(self):
        client = application.app.test_client()
        cases = (
            ("ab", "ValidPassword123!", "ValidPassword123!"),
            ("bad name", "ValidPassword123!", "ValidPassword123!"),
            ("valid_name", "short", "short"),
            ("valid_name", "ValidPassword123!", "DifferentPassword!"),
            ("TEST_OWNER", "ValidPassword123!", "ValidPassword123!"),
        )
        for username, password, confirmation in cases:
            with self.subTest(username=username):
                response = self.post("/register", {
                    "username": username, "password": password,
                    "confirm_password": confirmation,
                }, client=client)
                self.assertEqual(response.status_code, 400)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 3)

    def test_admin_routes_and_counts(self):
        self.assertEqual(self.client.get("/admin").status_code, 403)
        response = self.login("test_admin", "AdminPassword123!")
        self.assertTrue(response.headers["Location"].endswith("/admin"))
        page = self.client.get("/admin")
        self.assertEqual(page.status_code, 200)
        for username in ("test_owner", "other_owner", "test_admin"):
            self.assertIn(username, page.get_data(as_text=True))
        self.assertIn(b"UTC+08:00", page.data)
        with application.app.test_request_context():
            conn = self.connect()
            try:
                for row in conn.execute("SELECT password_hash FROM users"):
                    self.assertNotIn(row["password_hash"], page.get_data(as_text=True))
            finally:
                conn.close()
        self.assertTrue(self.client.get("/").headers["Location"].endswith("/admin"))
        before = self.snapshot()
        self.assertEqual(self.post("/add", self.valid_transaction()).status_code, 302)
        self.assertEqual(self.snapshot(), before)

    def test_missing_and_invalid_csrf_are_rejected(self):
        self.token()
        before = self.snapshot()
        for token in (None, "invalid-token"):
            for endpoint, fields in (
                ("/add", self.valid_transaction()),
                ("/", {"month": "2026-11", "budget": "100"}),
                ("/delete/1", {}), ("/logout", {}),
            ):
                with self.subTest(endpoint=endpoint, token=token):
                    data = dict(fields)
                    if token is not None:
                        data["csrf_token"] = token
                    self.assertEqual(self.client.post(endpoint, data=data).status_code, 400)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_registration_and_login_require_csrf(self):
        client = application.app.test_client()
        for endpoint in ("/login", "/register"):
            self.assertEqual(client.post(endpoint, data={
                "username": "test_owner", "password": "TestPassword123!",
                "confirm_password": "TestPassword123!",
            }).status_code, 400)

    def test_other_users_transactions_are_hidden_and_protected(self):
        own_id = self.insert_transaction("2026-11-18", "OwnerVisible", "10")
        other_id = self.insert_transaction("2026-11-18", "OtherPrivate", "999", user_id=self.other_id)
        page = self.client.get("/?month=2026-11").get_data(as_text=True)
        self.assertIn("OwnerVisible", page)
        self.assertNotIn("OtherPrivate", page)
        self.assertIn("Total expenses: CNY 10.00", page)
        before = self.snapshot()
        self.assertEqual(self.client.get(f"/edit/{other_id}").status_code, 404)
        self.assertEqual(self.post(f"/edit/{other_id}", self.valid_transaction()).status_code, 404)
        self.assertEqual(self.post(f"/delete/{other_id}").status_code, 404)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get(f"/edit/{own_id}").status_code, 200)

    def test_forged_user_id_cannot_transfer_ownership(self):
        response = self.post("/add", self.valid_transaction(user_id=str(self.other_id)))
        self.assertEqual(response.status_code, 302)
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM account_transactions").fetchone()
        self.assertEqual(row["user_id"], self.user_id)

    def test_account_budgets_and_defaults_are_isolated(self):
        self.write_budget("2026-11", "100")
        self.write_budget("2026-11", "900", user_id=self.other_id)
        self.assertEqual(self.read_budget("2027-01"), "100.00")
        self.assertEqual(self.read_budget("2027-01", self.other_id), "900.00")
        self.assertEqual(self.post("/", {"month": "2026-11", "budget": "250", "user_id": self.other_id}).status_code, 302)
        self.assertEqual(self.read_budget("2027-01"), "250.00")
        self.assertEqual(self.read_budget("2027-01", self.other_id), "900.00")

    def test_private_pages_are_not_cached(self):
        for endpoint in ("/", "/add", "/login"):
            self.assertEqual(self.client.get(endpoint).headers.get("Cache-Control"), "no-store")

    def create_legacy_data(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("""CREATE TABLE transactions (
                id INTEGER PRIMARY KEY, date TEXT, category TEXT,
                amount REAL, type TEXT)""")
            conn.execute("CREATE TABLE monthly_budgets (month TEXT PRIMARY KEY, amount TEXT NOT NULL)")
            conn.execute("CREATE TABLE monthly_budget_defaults (month TEXT PRIMARY KEY, amount TEXT NOT NULL)")
            conn.execute("INSERT INTO transactions VALUES (1, '2026-11-18', 'LegacyRecord', 25.5, 'expense')")
            conn.execute("INSERT INTO monthly_budgets VALUES ('2026-11', '900.00')")
            conn.execute("INSERT INTO monthly_budget_defaults VALUES ('2026-11', '1200.00')")

    def test_legacy_import_keeps_originals_and_does_not_duplicate(self):
        self.create_legacy_data()
        with closing(self.connect()) as conn:
            self.assertTrue(import_legacy_data(conn, self.user_id))
            self.assertFalse(import_legacy_data(conn, self.user_id))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM account_transactions").fetchone()[0], 1)
            with self.assertRaises(ValueError):
                import_legacy_data(conn, self.other_id)
        self.assertEqual(self.read_budget("2026-11"), "900.00")
        self.assertEqual(self.read_budget("2026-12"), "1200.00")
        self.assertIsNone(self.read_budget("2026-12", self.other_id))

    def test_legacy_import_rejects_admin_and_used_account(self):
        self.create_legacy_data()
        self.insert_transaction("2026-11-18", "ExistingRecord", "10")
        before = self.snapshot()
        with closing(self.connect()) as conn:
            for user_id in (self.admin_id, self.user_id):
                with self.subTest(user_id=user_id), self.assertRaises(ValueError):
                    import_legacy_data(conn, user_id)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_import_failure_rolls_back_every_copy(self):
        self.create_legacy_data()
        with closing(self.connect()) as conn, conn:
            conn.execute("""CREATE TRIGGER reject_import BEFORE INSERT ON account_budget_defaults
                BEGIN SELECT RAISE(ABORT, 'Simulated import failure'); END""")
        with closing(self.connect()) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                import_legacy_data(conn, self.user_id)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM account_migrations").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)
        self.assertEqual(self.snapshot(), {
            "account_transactions": [], "account_monthly_budgets": [],
            "account_budget_defaults": [],
        })
