# Personal Finance Manager

A simple web application for managing personal finances. Track your expenses and incomes with ease using this tool.

## Features

- **Add, Edit, and Delete Transactions:** Manage your financial records effectively.
- **Categorize Transactions:** Differentiate between expenses and incomes with categories.
- **User-friendly Interface:** Easy to navigate and manage transactions.

## Technologies Used

- **Frontend:** HTML, CSS, JavaScript
- **Backend:** Python (Flask)
- **Database:** SQLite

## Installation For Termux(Android) and Debian based OS

Follow these steps to set up the project locally.

### Prerequisites

- **Python 3.x**: Ensure Python is installed on your system. Download it from [python.org](https://www.python.org/).
- **SQLite**: Comes pre-installed with Python, but you can get more info [here](https://www.sqlite.org/index.html).


# Instructions for Android Systems

### If you are using TERMUX on Android then use these command for installing Python and SQLite  
```bash
pkg update && pkg upgrade
```
```bash
pkg install python sqlite
```
### Clone the Repository

Clone the repository to your local machine using the following command:

```bash
git clone https://github.com/pravashdas/personal-finance-manager.git
cd personal-finance-manager

```

### Dependencies Installation
```bash 
pip install -r requirements.txt
```

### Give the Permission before run the Application
```bash 
chmod +x run_app.sh
```

### Running the Application
```bash 
./run_app.sh
```

### Alternatively, you can manually set the environment variable and start the Flask server:
 
`export FLASK_APP=app.py`
`flask run --host=0.0.0.0`


### Access the application in your web browser at
`http://localhost:5000`

# Instructions for Debian-based Systems
### Update the Package List and Upgrade Installed Packages
```bash
sudo apt update && sudo apt upgrade
```

### Install Python and SQLite
```bash
sudo apt install python3 sqlite3
```

### Clone the Repository
```bash
git clone https://github.com/pravashdas/personal-finance-manager.git
```
```bash
cd personal-finance-manager
```

### Install Dependencies
```bash
pip install -r requirements.txt
```
### Give Permission to Run the Application
```bash
chmod +x run_app.sh
```

### Running the Application
```bash
./run_app.sh
```
### Alternatively, you can manually set the environment variable and start the Flask server:
`export FLASK_APP=app.py`
`flask run --host=0.0.0.0`

### Access the application in your web browser at
`http://localhost:5000`



# Instructions for Windows Systems

### Install Python and SQLite

1. Download and install Python from the official website: https://www.python.org/downloads/
2. Download and install SQLite from the official website: https://www.sqlite.org/download.html

### Clone the Repository
``` bash
git clone https://github.com/pravashdas/personal-finance-manager.git
```

``` bash
cd personal-finance-manager
```

### Install Dependencies
``` bash
pip install -r requirements.txt
```


### Running the Application

If using Command Prompt or PowerShell:
``` bash
python run_app.py
```
### Alternatively, you can manually set the environment variable and start the Flask server:
``` bash
set FLASK_APP=app.py
flask run --host=0.0.0.0
``` 

### Access the application in your web browser at
``` bash
http://localhost:5000
``` 

## Month selection — Issue #3

The homepage defaults to the current month. Select a month and click
"Show transactions" to view its records. Empty months show a message;
invalid month parameters return HTTP 400 without changing stored data.

Run the automated tests from the project root after installing dependencies:

```bash
python -m unittest -v test_month_selection
```

The seven tests cover month boundaries, year isolation, empty months,
selection retention, the current-month default, invalid parameters,
and unchanged database contents. Tests use a temporary SQLite database.

## Monthly budgets — Issue #5

Select a month, enter a non-negative budget with at most two decimal
places, and click "Save budget". Budgets are stored separately by year
and month and displayed in CNY with two decimal places.
An unset budget is distinguished from 0.00.

The monthly_budgets table is created automatically in finance.db.
Saved budgets persist across application restarts.

Run the month-selection and monthly-budget tests:

```bash
python -m unittest -v test_month_selection test_monthly_budget
```

Tests use temporary SQLite databases and cover saving, updating,
month/year isolation, zero and unset budgets, invalid input,
persistence after reopening the database, and rollback on save failure.

## Monthly spending summary — Issue #7

The selected month's summary shows total expenses, excluding income.
When a monthly budget is set, remaining budget equals budget minus expenses.
Overspending displays a negative remaining budget and a clear alert.
Spending exactly the budget does not trigger an alert.

An unset budget is distinguished from a budget of 0.00.
Months without expenses show CNY 0.00. All amounts use two decimal places.
The summary is recalculated when the page loads, reflecting saved changes
to transactions and budgets.

Run the regression and monthly-summary tests:

```bash
python -m unittest -v test_month_selection test_monthly_budget test_monthly_summary
```

Tests use temporary SQLite databases and cover expense-only totals,
month/year isolation, empty months, unset and zero budgets, exact-budget
and overspending cases, decimal amounts, and recalculation after
transaction and budget changes.

## Transaction input validation — Issue #9

Adding and editing transactions use shared server-side validation.
Dates must be valid calendar dates in YYYY-MM-DD format.
Categories must not be empty after trimming whitespace.
Amounts must be positive, with at most two decimal places.
Non-numeric amounts, NaN, Infinity, and scientific notation are rejected.
Transaction type must be expense or income.

Invalid submissions return HTTP 400, display clear errors, and preserve
entered values without inserting or changing stored transactions.
Editing a missing transaction returns HTTP 404.

Run all four test modules:

```bash
python -m unittest -v test_month_selection test_monthly_budget test_monthly_summary test_transaction_validation
```

Validation tests use a temporary SQLite database and cover valid adds
and edits, invalid and missing fields, unchanged stored data after
rejection, input retention, whitespace trimming, amount normalization,
leap dates, form loading, and missing transactions.

### Desktop interface and budget inheritance

- Use a consistent desktop layout for the home, add, and edit pages.
- Add transactions from the Transactions section.
- Edit monthly budgets within the Monthly budget summary card.
- Default new transaction dates to today, with a day-level calendar picker.
- Budgets saved for the current or a future month apply from that month
  until a later saved default takes effect.
- Editing a past month changes only that month.
- Zero is a valid budget and can be inherited.
- Existing saved budgets are retained during automatic migration.

Validation:
python -m unittest -v test_month_selection test_monthly_budget test_monthly_summary test_transaction_validation test_budget_inheritance

All 47 tests passed.

### Accounts and access

- Register a regular user account through the registration page.
- Log in with a username and password.
- Regular users can access only their own transactions and budgets.
- Administrators can view account counts, usernames, registration
  times, and roles. Registration times display in Beijing time
  (UTC+08:00).
- Administrator accounts are created locally:

  python -m flask --app app create-account --admin --username admin

- Existing financial data can be imported once into a regular account:

  python -m flask --app app import-existing-data --username USERNAME

- Original financial tables are retained after import.
- Passwords are stored as hashes.
- POST forms require a CSRF token.
- The local session key is stored in the ignored instance directory.

### Run all tests

python -m unittest discover -s tests -v

All 64 tests passed on Windows with Python 3.13.
Tests use temporary databases without modifying finance.db.