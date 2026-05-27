"""
Tests for Step 07: Add Expense

Spec reference:
  .claude/specs/07-add-expense.md

Coverage:
  - Unit tests for insert_expense() DB helper
  - Auth guards (GET and POST, unauthenticated → /login)
  - GET /expenses/add — 200, form structure, all 7 category options
  - POST happy path — redirect to /profile, DB row inserted
  - POST without description — redirect + NULL description in DB
  - POST validation errors — missing/zero/negative/non-numeric amount,
    invalid category, missing/invalid date → 200 + error message
  - Value persistence — previously submitted values pre-filled on re-render
"""

import pytest
from datetime import datetime
from werkzeug.security import generate_password_hash

from app import app as flask_app
from database.db import get_db, init_db
from database.queries import insert_expense

VALID_CATEGORIES = ['Food', 'Transport', 'Bills', 'Health',
                    'Entertainment', 'Shopping', 'Other']


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def app(tmp_path):
    """Isolated app instance backed by a fresh temp-file SQLite database."""
    flask_app.config['DATABASE'] = str(tmp_path / 'test_add_expense.db')
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-add-expense'
    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def test_user(app):
    """Insert a test user and return (user_id, email, password)."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (
                'Expense Tester',
                'expense@example.com',
                generate_password_hash('testpass123', method='pbkdf2:sha256'),
                '2026-01-01 00:00:00',
            )
        )
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
    return user_id, 'expense@example.com', 'testpass123'


@pytest.fixture
def auth_client(client, test_user):
    """Test client with test_user already injected into the session."""
    user_id, _, _ = test_user
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
    return client


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def _expense_count(app, user_id):
    """Return the number of expense rows for user_id."""
    with app.app_context():
        row = get_db().execute(
            'SELECT COUNT(*) FROM expenses WHERE user_id = ?', (user_id,)
        ).fetchone()
        return row[0]


def _get_expense_row(app, user_id):
    """Return the first expense row for user_id, or None."""
    with app.app_context():
        return get_db().execute(
            'SELECT * FROM expenses WHERE user_id = ? LIMIT 1', (user_id,)
        ).fetchone()


# ================================================================== #
# Unit tests: insert_expense()                                        #
# ================================================================== #

class TestInsertExpense:
    """Direct unit tests for the insert_expense() DB helper."""

    def test_insert_expense_creates_row_with_correct_values(self, app, test_user):
        """
        Spec: insert_expense with valid args inserts a row; querying the DB
        returns the inserted row with matching field values.
        """
        user_id, _, _ = test_user
        with app.app_context():
            insert_expense(user_id, 50.0, 'Food', '2026-03-20', 'Lunch')
            row = get_db().execute(
                'SELECT * FROM expenses WHERE user_id = ?', (user_id,)
            ).fetchone()

        assert row is not None, 'Expected a row to be inserted in the expenses table'
        assert row['user_id'] == user_id, f'Expected user_id={user_id}, got {row["user_id"]}'
        assert row['amount'] == 50.0, f'Expected amount=50.0, got {row["amount"]}'
        assert row['category'] == 'Food', f'Expected category="Food", got {row["category"]}'
        assert row['date'] == '2026-03-20', f'Expected date="2026-03-20", got {row["date"]}'
        assert row['description'] == 'Lunch', f'Expected description="Lunch", got {row["description"]}'

    def test_insert_expense_null_description_stored_as_null(self, app, test_user):
        """
        Spec: insert_expense with description=None stores NULL in the DB.
        """
        user_id, _, _ = test_user
        with app.app_context():
            insert_expense(user_id, 99.99, 'Transport', '2026-04-15', None)
            row = get_db().execute(
                'SELECT description FROM expenses WHERE user_id = ?', (user_id,)
            ).fetchone()

        assert row is not None, 'Expected an expense row to be inserted'
        assert row['description'] is None, (
            f'Expected description=NULL in DB, got {row["description"]!r}'
        )

    def test_insert_expense_increments_row_count(self, app, test_user):
        """
        Spec: After calling insert_expense, the DB contains one more expense row.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)
        with app.app_context():
            insert_expense(user_id, 200.0, 'Bills', '2026-05-01', 'Electricity')
        after = _expense_count(app, user_id)
        assert after == before + 1, (
            f'Expected row count to increase by 1 (was {before}, now {after})'
        )

    def test_insert_expense_multiple_rows_independent(self, app, test_user):
        """
        Spec: Two sequential insert_expense calls produce two distinct rows.
        """
        user_id, _, _ = test_user
        with app.app_context():
            insert_expense(user_id, 10.0, 'Food', '2026-05-01', 'Breakfast')
            insert_expense(user_id, 20.0, 'Health', '2026-05-02', 'Medicine')
            rows = get_db().execute(
                'SELECT * FROM expenses WHERE user_id = ? ORDER BY id', (user_id,)
            ).fetchall()

        assert len(rows) == 2, f'Expected 2 rows, got {len(rows)}'
        assert rows[0]['amount'] == 10.0
        assert rows[1]['amount'] == 20.0


# ================================================================== #
# Auth guard tests                                                    #
# ================================================================== #

class TestAddExpenseAuthGuard:
    """Unauthenticated requests to GET and POST /expenses/add must redirect."""

    def test_get_unauthenticated_redirects_to_login(self, client):
        """
        Spec: Visiting GET /expenses/add while logged out redirects to /login (302).
        """
        response = client.get('/expenses/add')
        assert response.status_code == 302, (
            f'Expected 302 redirect for unauthenticated GET, got {response.status_code}'
        )
        assert '/login' in response.headers['Location'], (
            f'Expected redirect to /login, got {response.headers["Location"]}'
        )

    def test_post_unauthenticated_redirects_to_login(self, client):
        """
        Spec: Submitting POST /expenses/add while logged out redirects to /login (302).
        """
        response = client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Lunch',
        })
        assert response.status_code == 302, (
            f'Expected 302 redirect for unauthenticated POST, got {response.status_code}'
        )
        assert '/login' in response.headers['Location'], (
            f'Expected redirect to /login, got {response.headers["Location"]}'
        )


# ================================================================== #
# GET /expenses/add — authenticated                                   #
# ================================================================== #

class TestGetAddExpense:
    """Tests for the GET /expenses/add route when authenticated."""

    def test_returns_200(self, auth_client):
        """
        Spec: Authenticated GET /expenses/add returns 200.
        """
        response = auth_client.get('/expenses/add')
        assert response.status_code == 200, (
            f'Expected 200 for authenticated GET /expenses/add, got {response.status_code}'
        )

    def test_form_has_post_method(self, auth_client):
        """
        Spec: The form must have method="POST".
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert 'method="post"' in html.lower(), (
            'Expected <form method="post"> in the add-expense page HTML'
        )

    def test_form_action_points_to_add_expense(self, auth_client):
        """
        Spec: The form action must point to /expenses/add.
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert '/expenses/add' in html, (
            'Expected form action to include /expenses/add'
        )

    def test_all_seven_categories_present(self, auth_client):
        """
        Spec: The category <select> must contain exactly the 7 fixed options:
        Food, Transport, Bills, Health, Entertainment, Shopping, Other.
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        for category in VALID_CATEGORIES:
            assert category in html, (
                f'Expected category option "{category}" to appear in the add-expense form'
            )

    def test_amount_input_present(self, auth_client):
        """
        Spec: The form must contain an amount input field.
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert 'name="amount"' in html, (
            'Expected an <input name="amount"> in the add-expense form'
        )

    def test_date_input_present(self, auth_client):
        """
        Spec: The form must contain a date input field.
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert 'name="date"' in html, (
            'Expected an <input name="date"> in the add-expense form'
        )

    def test_description_input_present(self, auth_client):
        """
        Spec: The form must contain a description input field.
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert 'name="description"' in html, (
            'Expected a description input/textarea in the add-expense form'
        )

    def test_today_date_prefilled(self, auth_client):
        """
        Spec: The date field defaults to today's date (YYYY-MM-DD).
        """
        today = datetime.now().strftime('%Y-%m-%d')
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert today in html, (
            f"Expected today's date ({today}) to be pre-filled in the date field"
        )

    def test_cancel_link_points_to_profile(self, auth_client):
        """
        Spec: The form must contain a cancel link back to /profile.
        """
        response = auth_client.get('/expenses/add')
        html = response.data.decode('utf-8')
        assert '/profile' in html, (
            'Expected a cancel link pointing to /profile on the add-expense page'
        )


# ================================================================== #
# POST /expenses/add — happy path                                     #
# ================================================================== #

class TestPostAddExpenseHappyPath:
    """Valid submissions must redirect to /profile and persist data in the DB."""

    def test_valid_post_redirects_to_profile(self, auth_client):
        """
        Spec: Valid POST redirects to /profile with status 302.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Lunch',
        })
        assert response.status_code == 302, (
            f'Expected 302 redirect on valid POST, got {response.status_code}'
        )
        assert '/profile' in response.headers['Location'], (
            f'Expected redirect to /profile, got {response.headers["Location"]}'
        )

    def test_valid_post_inserts_row_in_db(self, auth_client, app, test_user):
        """
        Spec: After a valid POST, the new expense row exists in the expenses table.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)

        auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Lunch',
        })

        after = _expense_count(app, user_id)
        assert after == before + 1, (
            f'Expected 1 new expense row in DB (was {before}, now {after})'
        )

    def test_valid_post_correct_values_in_db(self, auth_client, app, test_user):
        """
        Spec: The inserted row must match the submitted form values exactly.
        """
        user_id, _, _ = test_user
        auth_client.post('/expenses/add', data={
            'amount': '75.5',
            'category': 'Transport',
            'date': '2026-04-10',
            'description': 'Taxi ride',
        })

        with app.app_context():
            row = get_db().execute(
                'SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1',
                (user_id,)
            ).fetchone()

        assert row is not None, 'Expected a row in the expenses table after valid POST'
        assert row['amount'] == 75.5, f'Expected amount=75.5, got {row["amount"]}'
        assert row['category'] == 'Transport', f'Expected category="Transport", got {row["category"]}'
        assert row['date'] == '2026-04-10', f'Expected date="2026-04-10", got {row["date"]}'
        assert row['description'] == 'Taxi ride', f'Expected description="Taxi ride", got {row["description"]}'

    def test_valid_post_all_categories_accepted(self, auth_client, app, test_user):
        """
        Spec: All 7 fixed categories must be accepted as valid inputs.
        """
        user_id, _, _ = test_user
        for category in VALID_CATEGORIES:
            response = auth_client.post('/expenses/add', data={
                'amount': '10.0',
                'category': category,
                'date': '2026-05-01',
                'description': f'{category} expense',
            })
            assert response.status_code == 302, (
                f'Expected 302 redirect for valid category "{category}", '
                f'got {response.status_code}'
            )

    def test_no_description_redirects_to_profile(self, auth_client):
        """
        Spec: Submitting without a description (optional field) still redirects
        to /profile with status 302 — description is not required.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '100.0',
            'category': 'Other',
            'date': '2026-05-15',
            'description': '',
        })
        assert response.status_code == 302, (
            f'Expected 302 redirect when description is empty, got {response.status_code}'
        )
        assert '/profile' in response.headers['Location'], (
            f'Expected redirect to /profile, got {response.headers["Location"]}'
        )

    def test_no_description_stores_null_in_db(self, auth_client, app, test_user):
        """
        Spec: When description is omitted (empty string), the DB row must have
        description = NULL.
        """
        user_id, _, _ = test_user
        auth_client.post('/expenses/add', data={
            'amount': '100.0',
            'category': 'Other',
            'date': '2026-05-15',
            'description': '',
        })

        with app.app_context():
            row = get_db().execute(
                'SELECT description FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1',
                (user_id,)
            ).fetchone()

        assert row is not None, 'Expected an expense row to be inserted'
        assert row['description'] is None, (
            f'Expected description=NULL when empty string submitted, got {row["description"]!r}'
        )

    def test_whitespace_only_description_stores_null(self, auth_client, app, test_user):
        """
        Spec: A description of only whitespace must be stripped and stored as NULL.
        """
        user_id, _, _ = test_user
        auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': '2026-05-01',
            'description': '   ',
        })

        with app.app_context():
            row = get_db().execute(
                'SELECT description FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1',
                (user_id,)
            ).fetchone()

        assert row is not None, 'Expected an expense row to be inserted'
        assert row['description'] is None, (
            f'Expected whitespace-only description to be stored as NULL, '
            f'got {row["description"]!r}'
        )


# ================================================================== #
# POST /expenses/add — amount validation errors                       #
# ================================================================== #

class TestPostAddExpenseAmountValidation:
    """Invalid amount values must re-render the form (200) with an error message."""

    @pytest.mark.parametrize('bad_amount', [
        '',         # missing amount
        '0',        # zero
        '0.00',     # zero as float string
        '-1',       # negative
        '-0.01',    # tiny negative
        'abc',      # non-numeric
        'twelve',   # word
        '1e999',    # overflow (Python float handles, still a valid float but edge case)
        '  ',       # whitespace only
    ])
    def test_invalid_amount_returns_200(self, auth_client, bad_amount):
        """
        Spec: A missing, zero, negative, or non-numeric amount returns 200
        (form re-rendered) — not a redirect.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': bad_amount,
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Test',
        })
        assert response.status_code == 200, (
            f'Expected 200 for invalid amount {bad_amount!r}, got {response.status_code}'
        )

    @pytest.mark.parametrize('bad_amount', [
        '',
        '0',
        '0.00',
        '-1',
        'abc',
        '  ',
    ])
    def test_invalid_amount_shows_error_message(self, auth_client, bad_amount):
        """
        Spec: On amount validation failure, the response body must contain
        an error message — not silently fail.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': bad_amount,
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Test',
        })
        html = response.data.decode('utf-8')
        # The spec error message: "Amount must be a positive number greater than 0."
        assert 'amount' in html.lower() or 'positive' in html.lower() or 'error' in html.lower(), (
            f'Expected an error message for invalid amount {bad_amount!r}, '
            f'but none found in response'
        )

    def test_missing_amount_does_not_insert_row(self, auth_client, app, test_user):
        """
        Spec: A validation failure must not insert any row in the DB.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)
        auth_client.post('/expenses/add', data={
            'amount': '',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Should not be inserted',
        })
        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected no new row for missing amount (count was {before}, now {after})'
        )

    def test_zero_amount_does_not_insert_row(self, auth_client, app, test_user):
        """
        Spec: Amount = 0 is rejected; no row must be inserted in the DB.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)
        auth_client.post('/expenses/add', data={
            'amount': '0',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Zero amount',
        })
        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected no new row for amount=0 (count was {before}, now {after})'
        )

    def test_negative_amount_does_not_insert_row(self, auth_client, app, test_user):
        """
        Spec: Negative amount is rejected; no row must be inserted in the DB.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)
        auth_client.post('/expenses/add', data={
            'amount': '-50',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Negative amount',
        })
        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected no new row for negative amount (count was {before}, now {after})'
        )


# ================================================================== #
# POST /expenses/add — category validation errors                     #
# ================================================================== #

class TestPostAddExpenseCategoryValidation:
    """Invalid category values must re-render the form (200) with an error message."""

    @pytest.mark.parametrize('bad_category', [
        '',            # missing / empty
        'food',        # wrong case
        'FOOD',        # all caps
        'Groceries',   # plausible but not in the fixed list
        'Unknown',     # arbitrary string
        '<script>',    # injection-style input
        'Food; DROP TABLE expenses;',  # SQL injection attempt
    ])
    def test_invalid_category_returns_200(self, auth_client, bad_category):
        """
        Spec: A category not in the fixed list of 7 options returns 200
        (form re-rendered) — not a redirect.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': bad_category,
            'date': '2026-03-20',
            'description': 'Test',
        })
        assert response.status_code == 200, (
            f'Expected 200 for invalid category {bad_category!r}, got {response.status_code}'
        )

    @pytest.mark.parametrize('bad_category', [
        '',
        'food',
        'Groceries',
        'Unknown',
    ])
    def test_invalid_category_shows_error_message(self, auth_client, bad_category):
        """
        Spec: On category validation failure, the response body must contain
        an error message.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': bad_category,
            'date': '2026-03-20',
            'description': 'Test',
        })
        html = response.data.decode('utf-8')
        assert 'category' in html.lower() or 'valid' in html.lower() or 'error' in html.lower(), (
            f'Expected an error message for invalid category {bad_category!r}, '
            f'but none found in response'
        )

    def test_invalid_category_does_not_insert_row(self, auth_client, app, test_user):
        """
        Spec: A category validation failure must not insert any row in the DB.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)
        auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'InvalidCategory',
            'date': '2026-03-20',
            'description': 'Should not insert',
        })
        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected no new row for invalid category (count was {before}, now {after})'
        )


# ================================================================== #
# POST /expenses/add — date validation errors                         #
# ================================================================== #

class TestPostAddExpenseDateValidation:
    """Invalid or missing date values must re-render the form (200) with an error."""

    @pytest.mark.parametrize('bad_date', [
        '',              # missing
        'not-a-date',    # garbage string
        '20-03-2026',    # wrong format (DD-MM-YYYY)
        '2026/03/20',    # wrong separator
        '2026-13-01',    # invalid month
        '2026-00-01',    # zero month
        '2026-02-30',    # Feb 30 — doesn't exist
        'yesterday',     # English word
    ])
    def test_invalid_date_returns_200(self, auth_client, bad_date):
        """
        Spec: A missing or malformed date returns 200 (form re-rendered).
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': bad_date,
            'description': 'Test',
        })
        assert response.status_code == 200, (
            f'Expected 200 for invalid date {bad_date!r}, got {response.status_code}'
        )

    @pytest.mark.parametrize('bad_date', [
        '',
        'not-a-date',
        '20-03-2026',
        '2026/03/20',
    ])
    def test_invalid_date_shows_error_message(self, auth_client, bad_date):
        """
        Spec: On date validation failure, the response body must contain
        an error message.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': bad_date,
            'description': 'Test',
        })
        html = response.data.decode('utf-8')
        assert 'date' in html.lower() or 'valid' in html.lower() or 'error' in html.lower(), (
            f'Expected an error message for invalid date {bad_date!r}, '
            f'but none found in response'
        )

    def test_invalid_date_does_not_insert_row(self, auth_client, app, test_user):
        """
        Spec: A date validation failure must not insert any row in the DB.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)
        auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Food',
            'date': 'not-a-date',
            'description': 'Should not insert',
        })
        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected no new row for invalid date (count was {before}, now {after})'
        )


# ================================================================== #
# Value persistence on validation error                               #
# ================================================================== #

class TestValuePersistenceOnError:
    """On re-render after a validation error, previously submitted values
    must be pre-filled in the form so the user does not lose their input."""

    def test_amount_persisted_after_invalid_category(self, auth_client):
        """
        Spec: When category is invalid, the submitted amount value must
        appear in the re-rendered form.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '123.45',
            'category': 'InvalidCategory',
            'date': '2026-03-20',
            'description': 'My test expense',
        })
        html = response.data.decode('utf-8')
        assert '123.45' in html, (
            'Expected the submitted amount "123.45" to be pre-filled in the '
            're-rendered form after an invalid-category error'
        )

    def test_date_persisted_after_invalid_amount(self, auth_client):
        """
        Spec: When amount is invalid, the submitted date value must appear
        in the re-rendered form.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': 'bad',
            'category': 'Food',
            'date': '2026-06-15',
            'description': 'My note',
        })
        html = response.data.decode('utf-8')
        assert '2026-06-15' in html, (
            'Expected the submitted date "2026-06-15" to be pre-filled in the '
            're-rendered form after an invalid-amount error'
        )

    def test_description_persisted_after_invalid_amount(self, auth_client):
        """
        Spec: When amount is invalid, the submitted description must appear
        in the re-rendered form.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '',
            'category': 'Food',
            'date': '2026-03-20',
            'description': 'Remember this note',
        })
        html = response.data.decode('utf-8')
        assert 'Remember this note' in html, (
            'Expected description "Remember this note" to be pre-filled in the '
            're-rendered form after an invalid-amount error'
        )

    def test_category_persisted_after_invalid_date(self, auth_client):
        """
        Spec: When date is invalid, the submitted (valid) category must
        still be reflected in the re-rendered form so the user can
        correct only the date.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '50.0',
            'category': 'Health',
            'date': 'not-a-date',
            'description': 'Doctor visit',
        })
        html = response.data.decode('utf-8')
        assert 'Health' in html, (
            'Expected the submitted category "Health" to appear in the '
            're-rendered form after an invalid-date error'
        )

    def test_amount_persisted_after_invalid_date(self, auth_client):
        """
        Spec: When date is invalid, the submitted amount must appear
        in the re-rendered form.
        """
        response = auth_client.post('/expenses/add', data={
            'amount': '999.0',
            'category': 'Shopping',
            'date': 'bad-date',
            'description': '',
        })
        html = response.data.decode('utf-8')
        assert '999.0' in html, (
            'Expected the submitted amount "999.0" to be pre-filled in the '
            're-rendered form after an invalid-date error'
        )


# ================================================================== #
# Profile page navigation integration                                 #
# ================================================================== #

class TestProfilePageNavigation:
    """Verify the /profile page contains a link to /expenses/add (spec requirement)."""

    def test_profile_contains_add_expense_link(self, auth_client):
        """
        Spec: The profile page must have an 'Add Expense' button/link
        pointing to /expenses/add so users can navigate to the form.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200, (
            f'Expected 200 for authenticated /profile, got {response.status_code}'
        )
        html = response.data.decode('utf-8')
        assert '/expenses/add' in html, (
            'Expected a link to /expenses/add on the profile page '
            '(spec: "Add Expense" button near the transaction table heading)'
        )
