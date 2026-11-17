from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import re
from datetime import date
from monthly_budget import (
    validate_month,
    get_monthly_budget,
    save_monthly_budget,
)

app = Flask(__name__)

# Database connection
def get_db_connection():
    conn = sqlite3.connect('finance.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/', methods=('GET', 'POST'))
def index():
    if request.method == 'POST':
        selected_month = request.form.get('month', '')
    else:
        selected_month = request.args.get(
            'month', date.today().strftime('%Y-%m')
        )

    error = None
    budget_error = None
    monthly_budget = None
    transactions = []
    status = 200

    if validate_month(selected_month):
        conn = get_db_connection()
        try:
            transactions = conn.execute(
                """SELECT * FROM transactions
                   WHERE substr(date, 1, 7) = ?
                   ORDER BY date, id""",
                (selected_month,)
            ).fetchall()

            monthly_budget = get_monthly_budget(conn, selected_month)

            if request.method == 'POST':
                try:
                    save_monthly_budget(
                        conn,
                        selected_month,
                        request.form.get('budget', '')
                    )
                except ValueError as exc:
                    budget_error = str(exc)
                    status = 400
                except sqlite3.Error:
                    budget_error = 'Budget could not be saved. Please try again.'
                    status = 503
                else:
                    return redirect(
                        url_for('index', month=selected_month)
                    )
        finally:
            conn.close()
    else:
        error = 'Invalid month. Use YYYY-MM with a year from 0001 to 9999.'
        selected_month = ''
        status = 400

    return render_template(
        'index.html',
        transactions=transactions,
        selected_month=selected_month,
        error=error,
        budget_error=budget_error,
        monthly_budget=(
            None if monthly_budget is None
            else format(monthly_budget, '.2f')
        )
    ), status

@app.route('/add', methods=('GET', 'POST'))
def add():
    if request.method == 'POST':
        date = request.form['date']
        category = request.form['category']
        amount = request.form['amount']
        type = request.form['type']  # 'expense' or 'income'

        conn = get_db_connection()
        conn.execute('INSERT INTO transactions (date, category, amount, type) VALUES (?, ?, ?, ?)',
                     (date, category, amount, type))
        conn.commit()
        conn.close()
        return redirect('/')

    return render_template('add.html')

@app.route('/delete/<int:id>', methods=('POST',))
def delete(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM transactions WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/edit/<int:id>', methods=('GET', 'POST'))
def edit(id):
    conn = get_db_connection()
    transaction = conn.execute('SELECT * FROM transactions WHERE id = ?', (id,)).fetchone()

    if request.method == 'POST':
        date = request.form['date']
        category = request.form['category']
        amount = request.form['amount']
        type = request.form['type']

        conn.execute('UPDATE transactions SET date = ?, category = ?, amount = ?, type = ? WHERE id = ?',
                     (date, category, amount, type, id))
        conn.commit()
        conn.close()
        return redirect('/')

    conn.close()
    return render_template('edit.html', transaction=transaction)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
