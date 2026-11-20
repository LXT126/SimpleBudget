"Authenticated fixtures: temporary databases, real login, real CSRF checks."
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app as application
from finance.account_storage import create_user, init_account_tables


class AccountTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "test.db"
        settings = patch.dict(application.app.config, TESTING=True)
        settings.start()
        self.addCleanup(settings.stop)
        connection_patch = patch.object(application, "get_db_connection", self.connect)
        connection_patch.start()
        self.addCleanup(connection_patch.stop)
        clock_patch = patch.object(application, "date", wraps=date)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.set_today(2026, 11)
        with closing(self.connect()) as conn:
            with conn:
                init_account_tables(conn)
            self.user_id = create_user(conn, "test_owner", "TestPassword123!")
            self.other_id = create_user(conn, "other_owner", "OtherPassword123!")
            self.admin_id = create_user(conn, "test_admin", "AdminPassword123!", "admin")
        self.client = application.app.test_client()
        self.login()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def set_today(self, year, month):
        self.clock.today.return_value = date(year, month, 18)

    def token(self, client=None):
        client = self.client if client is None else client
        response = client.get("/login")
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as state:
            token = state.get("csrf_token")
        self.assertTrue(token, "Login page must generate a CSRF token")
        return token

    def post(self, endpoint, data=None, client=None, **kwargs):
        client = self.client if client is None else client
        fields = dict(data or {})
        fields["csrf_token"] = self.token(client)
        return client.post(endpoint, data=fields, **kwargs)

    def login(self, username="test_owner", password="TestPassword123!", client=None):
        response = self.post("/login", {"username": username, "password": password}, client=client)
        self.assertEqual(response.status_code, 302)
        return response

    def insert_transaction(self, day, category, amount, kind="expense", user_id=None):
        user_id = self.user_id if user_id is None else user_id
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                """INSERT INTO account_transactions
                   (user_id, date, category, amount, type) VALUES (?, ?, ?, ?, ?)""",
                (user_id, day, category, amount, kind),
            )
            return cursor.lastrowid

    def read_budget(self, month="2026-11", user_id=None):
        user_id = self.user_id if user_id is None else user_id
        with closing(self.connect()) as conn:
            value = application.read_budget(conn, user_id, month)
        return None if value is None else format(value, ".2f")

    def write_budget(self, month, amount, user_id=None):
        user_id = self.user_id if user_id is None else user_id
        with closing(self.connect()) as conn:
            application.save_budget(conn, user_id, month, amount)
