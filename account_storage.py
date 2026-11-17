import sqlite3
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash


def init_account_tables(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT NOT NULL COLLATE NOCASE UNIQUE,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL
                   CHECK (role IN ('user', 'admin')),
               registered_at TEXT NOT NULL
           )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS account_transactions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL REFERENCES users(id),
               date TEXT NOT NULL,
               category TEXT NOT NULL,
               amount REAL NOT NULL,
               type TEXT NOT NULL
                   CHECK (type IN ('expense', 'income'))
           )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS account_monthly_budgets (
               user_id INTEGER NOT NULL REFERENCES users(id),
               month TEXT NOT NULL,
               amount TEXT NOT NULL,
               PRIMARY KEY (user_id, month)
           )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS account_budget_defaults (
               user_id INTEGER NOT NULL REFERENCES users(id),
               month TEXT NOT NULL,
               amount TEXT NOT NULL,
               PRIMARY KEY (user_id, month)
           )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS account_migrations (
               name TEXT PRIMARY KEY,
               owner_id INTEGER NOT NULL REFERENCES users(id),
               completed_at TEXT NOT NULL
           )"""
    )

    conn.execute(
        """CREATE INDEX IF NOT EXISTS account_transactions_user_date
           ON account_transactions (user_id, date)"""
    )


def validate_credentials(username, password):
    username = username.strip()

    if not 3 <= len(username) <= 40:
        raise ValueError("Username must contain 3 to 40 characters.")

    if not all(
        character.isascii()
        and (character.isalnum() or character in "_.-")
        for character in username
    ):
        raise ValueError(
            "Use letters, numbers, underscores, dots, or hyphens "
            "in the username."
        )

    if not 8 <= len(password) <= 128:
        raise ValueError("Password must contain 8 to 128 characters.")

    return username


def create_user(conn, username, password, role="user"):
    username = validate_credentials(username, password)

    if role not in ("user", "admin"):
        raise ValueError("Invalid account role.")

    password_hash = generate_password_hash(password)
    registered_at = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    with conn:
        cursor = conn.execute(
            """INSERT INTO users
               (username, password_hash, role, registered_at)
               VALUES (?, ?, ?, ?)""",
            (username, password_hash, role, registered_at)
        )

    return cursor.lastrowid


def import_legacy_data(conn, owner_id):
    """Import the original data once into a chosen regular account."""
    owner = conn.execute(
        "SELECT id, role FROM users WHERE id = ?",
        (owner_id,)
    ).fetchone()

    if owner is None or owner["role"] != "user":
        raise ValueError(
            "Existing financial data must belong to a regular user."
        )

    with conn:
        previous = conn.execute(
            """SELECT owner_id FROM account_migrations
               WHERE name = 'legacy_financial_data'"""
        ).fetchone()

        if previous is not None:
            if previous["owner_id"] != owner_id:
                raise ValueError(
                    "Existing data has already been imported "
                    "into another account."
                )
            return False

        # Refuse to combine legacy data with an already-used account.
        for table in (
            "account_transactions",
            "account_monthly_budgets",
            "account_budget_defaults",
        ):
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE user_id = ? LIMIT 1",
                (owner_id,)
            ).fetchone()

            if row is not None:
                raise ValueError(
                    "Choose an account without financial records "
                    "for the import."
                )

        conn.execute(
            """INSERT INTO account_transactions
               (user_id, date, category, amount, type)
               SELECT ?, date, category, amount, type
               FROM transactions
               ORDER BY id""",
            (owner_id,)
        )

        conn.execute(
            """INSERT INTO account_monthly_budgets
               (user_id, month, amount)
               SELECT ?, month, amount FROM monthly_budgets""",
            (owner_id,)
        )

        conn.execute(
            """INSERT INTO account_budget_defaults
               (user_id, month, amount)
               SELECT ?, month, amount FROM monthly_budget_defaults""",
            (owner_id,)
        )

        conn.execute(
            """INSERT INTO account_migrations
               (name, owner_id, completed_at)
               VALUES ('legacy_financial_data', ?, ?)""",
            (
                owner_id,
                datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            )
        )

    return True