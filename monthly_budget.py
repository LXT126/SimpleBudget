import re
from datetime import date
from decimal import Decimal


def validate_month(month):
    return (
        re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) is not None
        and int(month[:4]) >= 1
    )


def validate_budget(value):
    value = value.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise ValueError(
            "Enter a non-negative budget with at most two decimal places."
        )

    whole, _, fraction = value.partition(".")
    whole = whole.lstrip("0") or "0"
    return f"{whole}.{fraction.ljust(2, '0')}"


def init_budget_table(conn):
    # The original table stores budgets explicitly saved for a month.
    # The new table stores defaults that take effect from a given month.
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS monthly_budgets (
                   month TEXT PRIMARY KEY,
                   amount TEXT NOT NULL
               )"""
        )

        defaults_exist = conn.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'monthly_budget_defaults'"""
        ).fetchone()

        if defaults_exist is None:
            conn.execute(
                """CREATE TABLE monthly_budget_defaults (
                       month TEXT PRIMARY KEY,
                       amount TEXT NOT NULL
                   )"""
            )

            # Preserve existing saved budgets as starting points.
            # This migration runs only when the new table is created.
            conn.execute(
                """INSERT INTO monthly_budget_defaults (month, amount)
                   SELECT month, amount FROM monthly_budgets"""
            )


def get_monthly_budget(conn, month):
    if not validate_month(month):
        raise ValueError("Invalid month. Use YYYY-MM.")

    init_budget_table(conn)

    # A budget explicitly saved for this month takes priority.
    row = conn.execute(
        "SELECT amount FROM monthly_budgets WHERE month = ?",
        (month,)
    ).fetchone()

    if row is not None:
        return Decimal(row["amount"])

    # Otherwise, inherit the most recent applicable default.
    row = conn.execute(
        """SELECT amount FROM monthly_budget_defaults
           WHERE month <= ?
           ORDER BY month DESC
           LIMIT 1""",
        (month,)
    ).fetchone()

    return None if row is None else Decimal(row["amount"])


def save_monthly_budget(conn, month, value):
    if not validate_month(month):
        raise ValueError("Invalid month. Use YYYY-MM.")

    amount = validate_budget(value)
    current_month = date.today().strftime("%Y-%m")

    init_budget_table(conn)

    # Save the selected month and its default rule atomically.
    with conn:
        conn.execute(
            """INSERT INTO monthly_budgets (month, amount)
               VALUES (?, ?)
               ON CONFLICT(month)
               DO UPDATE SET amount = excluded.amount""",
            (month, amount)
        )

        if month >= current_month:
            conn.execute(
                """INSERT INTO monthly_budget_defaults (month, amount)
                   VALUES (?, ?)
                   ON CONFLICT(month)
                   DO UPDATE SET amount = excluded.amount""",
                (month, amount)
            )