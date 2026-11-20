import os
import secrets
import sqlite3
from datetime import date
from decimal import Decimal
from functools import wraps
from pathlib import Path

import click
from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from account_storage import (
    add_user_category,
    create_user,
    get_user_categories,
    import_legacy_data,
    init_account_tables,
)
from monthly_budget import validate_budget, validate_month
from monthly_summary import calculate_monthly_summary
from transaction_validation import validate_transaction


app = Flask(__name__)

secret_key = os.environ.get("SIMPLEBUDGET_SECRET_KEY")

if not secret_key:
    instance_dir = Path(app.instance_path)
    instance_dir.mkdir(parents=True, exist_ok=True)
    key_file = instance_dir / "session.key"

    try:
        with key_file.open("x", encoding="utf-8") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass

    secret_key = key_file.read_text(encoding="utf-8").strip()

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=1024 * 1024,
)


def get_db_connection():
    conn = sqlite3.connect("finance.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = get_db_connection()

        with g.db:
            init_account_tables(g.db)

    return g.db


@app.teardown_appcontext
def close_db(error=None):
    conn = g.pop("db", None)

    if conn is not None:
        conn.close()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def load_user_and_check_form():
    g.user = None

    if request.endpoint == "static":
        return

    user_id = session.get("user_id")

    if user_id is not None:
        g.user = get_db().execute(
            """SELECT id, username, role, registered_at
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()

        if g.user is None:
            session.clear()

    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "")

        if not expected or not secrets.compare_digest(
            expected,
            supplied,
        ):
            abort(
                400,
                description="Form expired. Reload the page and try again.",
            )


@app.after_request
def prevent_private_page_caching(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"

    return response


def user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))

        if g.user["role"] != "user":
            return redirect(url_for("admin"))

        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def provide_user_categories():
    return {
        "user_categories": (
            get_user_categories(get_db(), g.user["id"])
            if g.user is not None and g.user["role"] == "user"
            else []
        )
    }


def read_budget(conn, user_id, month):
    row = conn.execute(
        """SELECT amount FROM account_monthly_budgets
           WHERE user_id = ? AND month = ?""",
        (user_id, month),
    ).fetchone()

    if row is None:
        row = conn.execute(
            """SELECT amount FROM account_budget_defaults
               WHERE user_id = ? AND month <= ?
               ORDER BY month DESC LIMIT 1""",
            (user_id, month),
        ).fetchone()

    if row is None:
        return None

    return Decimal(row["amount"])


def save_budget(conn, user_id, month, value):
    if not validate_month(month):
        raise ValueError("Invalid month. Use YYYY-MM.")

    amount = validate_budget(value)

    with conn:
        conn.execute(
            """INSERT INTO account_monthly_budgets
               (user_id, month, amount) VALUES (?, ?, ?)
               ON CONFLICT(user_id, month)
               DO UPDATE SET amount = excluded.amount""",
            (user_id, month, amount),
        )

        if month >= date.today().strftime("%Y-%m"):
            conn.execute(
                """INSERT INTO account_budget_defaults
                   (user_id, month, amount) VALUES (?, ?, ?)
                   ON CONFLICT(user_id, month)
                   DO UPDATE SET amount = excluded.amount""",
                (user_id, month, amount),
            )


@app.route("/register", methods=("GET", "POST"))
def register():
    error = None
    username = ""
    status = 200

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")

        if password != confirmation:
            error = "Passwords do not match."
            status = 400
        else:
            try:
                create_user(
                    get_db(),
                    username,
                    password,
                    role="user",
                )
            except ValueError as exc:
                error = str(exc)
                status = 400
            except sqlite3.IntegrityError:
                error = "This username is already in use."
                status = 400
            else:
                return redirect(url_for("login", registered="1"))

    return render_template(
        "auth.html",
        registering=True,
        error=error,
        username=username,
    ), status


@app.route("/login", methods=("GET", "POST"))
def login():
    error = None
    username = ""
    status = 200

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if user is None or not check_password_hash(
            user["password_hash"],
            password,
        ):
            error = "Invalid username or password."
            status = 400
        else:
            session.clear()
            session["user_id"] = user["id"]

            return redirect(
                url_for(
                    "admin" if user["role"] == "admin" else "index"
                )
            )

    return render_template(
        "auth.html",
        registering=False,
        error=error,
        username=username,
    ), status


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin")
def admin():
    if g.user is None:
        return redirect(url_for("login"))

    if g.user["role"] != "admin":
        abort(403)

    users = get_db().execute(
        """SELECT id, username, role, registered_at
           FROM users ORDER BY registered_at DESC, id DESC"""
    ).fetchall()

    return render_template(
        "admin.html",
        users=users,
        regular_count=sum(
            user["role"] == "user" for user in users
        ),
        admin_count=sum(
            user["role"] == "admin" for user in users
        ),
    )


@app.route("/", methods=("GET", "POST"))
@user_required
def index():
    selected_month = (
        request.form.get("month", "")
        if request.method == "POST"
        else request.args.get(
            "month",
            date.today().strftime("%Y-%m"),
        )
    )

    error = None
    budget_error = None
    monthly_budget = None
    transactions = []
    status = 200

    if validate_month(selected_month):
        conn = get_db()
        user_id = g.user["id"]

        transactions = conn.execute(
            """SELECT * FROM account_transactions
               WHERE user_id = ? AND substr(date, 1, 7) = ?
               ORDER BY date, id""",
            (user_id, selected_month),
        ).fetchall()

        monthly_budget = read_budget(
            conn,
            user_id,
            selected_month,
        )

        if request.method == "POST":
            try:
                save_budget(
                    conn,
                    user_id,
                    selected_month,
                    request.form.get("budget", ""),
                )
            except ValueError as exc:
                budget_error = str(exc)
                status = 400
            except sqlite3.Error:
                budget_error = (
                    "Budget could not be saved. Please try again."
                )
                status = 503
            else:
                return redirect(
                    url_for("index", month=selected_month)
                )
    else:
        error = (
            "Invalid month. Use YYYY-MM with a year "
            "from 0001 to 9999."
        )
        selected_month = ""
        status = 400

    summary = calculate_monthly_summary(
        transactions,
        monthly_budget,
    )

    return render_template(
        "index.html",
        transactions=transactions,
        selected_month=selected_month,
        error=error,
        budget_error=budget_error,
        summary=summary,
        monthly_budget=(
            None
            if monthly_budget is None
            else format(monthly_budget, ".2f")
        ),
    ), status


@app.route("/category-budgets", methods=("GET", "POST"))
@user_required
def category_budgets():
    values = {
        "month": (
            request.form.get("month", "")
            if request.method == "POST"
            else request.args.get(
                "month",
                date.today().strftime("%Y-%m"),
            )
        ),
        "category": request.form.get("category", ""),
        "amount": request.form.get("amount", ""),
    }

    error = None
    status = 200
    valid_month = validate_month(values["month"])
    conn = get_db()

    if not valid_month:
        error = (
            "Invalid month. Use YYYY-MM with a year "
            "from 0001 to 9999."
        )
        status = 400

    elif request.method == "POST":
        try:
            category = values["category"].strip()

            if not category:
                raise ValueError("Enter a category.")

            amount = validate_budget(values["amount"])

            with conn:
                conn.execute(
                    """INSERT INTO account_category_budgets
                       (user_id, month, category, amount)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id, month, category)
                       DO UPDATE SET amount = excluded.amount""",
                    (
                        g.user["id"],
                        values["month"],
                        category,
                        amount,
                    ),
                )

        except ValueError as exc:
            error = str(exc)
            status = 400

        except sqlite3.Error:
            error = (
                "Category budget could not be saved. "
                "Please try again."
            )
            status = 503

        else:
            return redirect(
                url_for(
                    "category_budgets",
                    month=values["month"],
                )
            )

    saved = {}

    if valid_month:
        saved = dict(
            conn.execute(
                """SELECT category, amount
                   FROM account_category_budgets
                   WHERE user_id = ? AND month = ?""",
                (g.user["id"], values["month"]),
            ).fetchall()
        )

    categories = get_user_categories(
        conn,
        g.user["id"],
    )

    return render_template(
        "category_budgets.html",
        values=values,
        error=error,
        valid_month=valid_month,
        categories=categories,
        saved=saved,
    ), status


@app.post("/categories")
@user_required
def create_category():
    try:
        name = add_user_category(
            get_db(),
            g.user["id"],
            request.form.get("name", ""),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    except sqlite3.IntegrityError:
        return jsonify(
            error="This category already exists."
        ), 400

    except sqlite3.Error:
        return jsonify(
            error="Category could not be saved. Please try again."
        ), 503

    return jsonify(name=name), 201


@app.route("/add", methods=("GET", "POST"))
@user_required
def add():
    values = {
        "date": date.today().isoformat(),
        "category": "Groceries",
        "amount": "",
        "type": "expense",
    }

    errors = {}

    if request.method == "POST":
        values, cleaned, errors = validate_transaction(
            request.form
        )

        if not errors:
            conn = get_db()

            with conn:
                conn.execute(
                    """INSERT INTO account_transactions
                       (user_id, date, category, amount, type)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        g.user["id"],
                        cleaned["date"],
                        cleaned["category"],
                        cleaned["amount"],
                        cleaned["type"],
                    ),
                )

            return redirect(
                url_for("index", month=cleaned["date"][:7])
            )

    return render_template(
        "add.html",
        values=values,
        errors=errors,
    ), 400 if errors else 200


@app.route("/edit/<int:id>", methods=("GET", "POST"))
@user_required
def edit(id):
    conn = get_db()

    transaction = conn.execute(
        """SELECT * FROM account_transactions
           WHERE id = ? AND user_id = ?""",
        (id, g.user["id"]),
    ).fetchone()

    if transaction is None:
        abort(404, description="Transaction not found.")

    values = {
        field: str(transaction[field])
        for field in ("date", "category", "amount", "type")
    }

    errors = {}

    if request.method == "POST":
        values, cleaned, errors = validate_transaction(
            request.form
        )

        if not errors:
            with conn:
                conn.execute(
                    """UPDATE account_transactions
                       SET date = ?, category = ?, amount = ?, type = ?
                       WHERE id = ? AND user_id = ?""",
                    (
                        cleaned["date"],
                        cleaned["category"],
                        cleaned["amount"],
                        cleaned["type"],
                        id,
                        g.user["id"],
                    ),
                )

            return redirect(
                url_for("index", month=cleaned["date"][:7])
            )

    return render_template(
        "edit.html",
        transaction=transaction,
        values=values,
        errors=errors,
    ), 400 if errors else 200


@app.post("/delete/<int:id>")
@user_required
def delete(id):
    conn = get_db()

    transaction = conn.execute(
        """SELECT date FROM account_transactions
           WHERE id = ? AND user_id = ?""",
        (id, g.user["id"]),
    ).fetchone()

    if transaction is None:
        abort(404, description="Transaction not found.")

    with conn:
        conn.execute(
            """DELETE FROM account_transactions
               WHERE id = ? AND user_id = ?""",
            (id, g.user["id"]),
        )

    return redirect(
        url_for("index", month=transaction["date"][:7])
    )


@app.cli.command("create-account")
@click.option("--admin", "is_admin", is_flag=True)
@click.option("--username", prompt=True)
@click.password_option()
def create_account_command(is_admin, username, password):
    """Create an account locally."""
    try:
        create_user(
            get_db(),
            username,
            password,
            role="admin" if is_admin else "user",
        )
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise click.ClickException(
            "Username already exists."
            if isinstance(exc, sqlite3.IntegrityError)
            else str(exc)
        ) from exc

    click.echo("Account created.")


@app.cli.command("import-existing-data")
@click.option("--username", prompt=True)
def import_existing_data_command(username):
    """Assign original financial data to a chosen regular account."""
    conn = get_db()

    user = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (username.strip(),),
    ).fetchone()

    if user is None:
        raise click.ClickException("Account not found.")

    try:
        imported = import_legacy_data(conn, user["id"])
    except (ValueError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        "Existing data imported."
        if imported
        else "Already imported; no duplicate records created."
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)