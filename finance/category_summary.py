"""Category expense summaries independent of overall monthly budgets."""

from decimal import Decimal

from finance.account_storage import DEFAULT_CATEGORIES
from finance.monthly_budget import validate_month


def calculate_category_summary(transactions, budgets, categories=()):
    totals = {}
    names = set(categories) | set(budgets)

    for transaction in transactions:
        category = transaction["category"]
        names.add(category)

        if transaction["type"] == "expense":
            totals[category] = (
                totals.get(category, Decimal("0"))
                + Decimal(str(transaction["amount"]))
            )

    rows = []

    for category in sorted(names, key=str.casefold):
        expenses = totals.get(category, Decimal("0"))
        raw_budget = budgets.get(category)

        budget = (
            None
            if raw_budget is None
            else Decimal(str(raw_budget))
        )

        remaining = (
            None
            if budget is None
            else budget - expenses
        )

        overspent = remaining is not None and remaining < 0

        status = (
            "No budget" if budget is None else
            "Overspent" if overspent else
            "At budget" if remaining == 0 else
            "Within budget"
        )

        rows.append(
            {
                "category": category,
                "budget": (
                    None
                    if budget is None
                    else format(budget, ".2f")
                ),
                "expenses": format(expenses, ".2f"),
                "remaining": (
                    None
                    if remaining is None
                    else format(remaining, ".2f")
                ),
                "overspent": overspent,
                "status": status,
            }
        )

    return rows


def read_category_summary(conn, user_id, month):
    if not validate_month(month):
        raise ValueError("Invalid month. Use YYYY-MM.")

    transactions = conn.execute(
        """SELECT category, amount, type
           FROM account_transactions
           WHERE user_id = ? AND substr(date, 1, 7) = ?""",
        (user_id, month),
    ).fetchall()

    budgets = dict(
        conn.execute(
            """SELECT category, amount
               FROM account_category_budgets
               WHERE user_id = ? AND month = ?""",
            (user_id, month),
        ).fetchall()
    )

    # Defaults and explicitly created personal categories are reusable.
    # Categories found only in historical records are not added here.
    categories = set(DEFAULT_CATEGORIES)

    categories.update(
        row["name"]
        for row in conn.execute(
            """SELECT name FROM account_categories
               WHERE user_id = ?""",
            (user_id,),
        )
    )

    return calculate_category_summary(
        transactions,
        budgets,
        categories,
    )