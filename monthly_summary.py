from decimal import Decimal


def calculate_monthly_summary(transactions, monthly_budget):
    total_expenses = sum(
        (
            Decimal(str(transaction["amount"]))
            for transaction in transactions
            if transaction["type"] == "expense"
        ),
        Decimal("0.00"),
    )

    remaining_budget = (
        None
        if monthly_budget is None
        else monthly_budget - total_expenses
    )

    return {
        "total_expenses": format(total_expenses, ".2f"),
        "remaining_budget": (
            None
            if remaining_budget is None
            else format(remaining_budget, ".2f")
        ),
        "overspent": (
            remaining_budget is not None and remaining_budget < 0
        ),
    }