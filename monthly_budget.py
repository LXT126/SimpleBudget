import re
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

    # Format directly from the input digits, without floating-point rounding.
    whole, _, fraction = value.partition(".")
    whole = whole.lstrip("0") or "0"
    return f"{whole}.{fraction.ljust(2, '0')}"


def init_budget_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS monthly_budgets (
               month TEXT PRIMARY KEY,
               amount TEXT NOT NULL
           )"""
    )


def get_monthly_budget(conn, month):
    init_budget_table(conn)
    row = conn.execute(
        "SELECT amount FROM monthly_budgets WHERE month = ?",
        (month,)
    ).fetchone()
    return None if row is None else Decimal(row["amount"])


def save_monthly_budget(conn, month, value):
    if not validate_month(month):
        raise ValueError("Invalid month. Use YYYY-MM.")

    amount = validate_budget(value)

    # Commit everything together; roll back if saving fails.
    with conn:
        init_budget_table(conn)
        conn.execute(
            """INSERT INTO monthly_budgets (month, amount)
               VALUES (?, ?)
               ON CONFLICT(month) DO UPDATE SET amount = excluded.amount""",
            (month, amount)
        )