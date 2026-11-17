import re
from datetime import date
from decimal import Decimal


def validate_transaction(form):
    values = {
        field: form.get(field, "")
        for field in ("date", "category", "amount", "type")
    }
    cleaned = {
        field: value.strip()
        for field, value in values.items()
    }
    errors = {}

    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", cleaned["date"]
    ):
        errors["date"] = "Enter a valid date in YYYY-MM-DD format."
    else:
        try:
            date.fromisoformat(cleaned["date"])
        except ValueError:
            errors["date"] = "Enter a valid calendar date."

    if not cleaned["category"]:
        errors["category"] = "Choose a category."

    amount = cleaned["amount"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", amount):
        errors["amount"] = (
            "Enter a positive amount with at most two decimal places."
        )
    elif Decimal(amount) <= 0:
        errors["amount"] = "Amount must be greater than zero."
    else:
        whole, _, fraction = amount.partition(".")
        whole = whole.lstrip("0") or "0"
        cleaned["amount"] = f"{whole}.{fraction.ljust(2, '0')}"

    if cleaned["type"] not in ("expense", "income"):
        errors["type"] = "Choose expense or income."

    return values, cleaned, errors