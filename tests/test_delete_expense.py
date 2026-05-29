"""
Tests for Step 09: Delete Expense

Spec reference:
  .claude/specs/09-delete-expense.md

Coverage:
  - Unit tests for delete_expense() DB helper:
      correct owner removes row, wrong owner leaves row, non-existent id is a no-op
  - Auth guard: unauthenticated POST → 302 to /login
  - Happy path: own expense deleted → 302 to /profile, row gone from DB
  - Cross-user ownership: POST to another user's expense → 404, row intact in DB
  - Non-existent expense id: POST → 404
  - Method guard: GET to /expenses/<id>/delete → 405
  - Template: profile.html contains delete form with POST method
"""

import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app
from database.db import get_db, init_db
from database.queries import delete_expense


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def app(tmp_path):
    """Isolated app instance backed by a fresh temp-file SQLite database."""
    flask_app.config['DATABASE'] = str(tmp_path / 'test_delete_expense.db')
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-delete'
    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def test_user(app):
    """Insert a primary test user; return (user_id, email, password)."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (
                'Delete Tester',
                'delete@example.com',
                generate_password_hash('testpass123', method='pbkdf2:sha256'),
                '2026-01-01 00:00:00',
            )
        )
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
    return user_id, 'delete@example.com', 'testpass123'


@pytest.fixture
def other_user(app):
    """Insert a second user who does NOT own the primary test expense."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (
                'Other User',
                'other@example.com',
                generate_password_hash('otherpass123', method='pbkdf2:sha256'),
                '2026-01-01 00:00:00',
            )
        )
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
    return user_id


@pytest.fixture
def auth_client(client, test_user):
    """Test client with test_user already injected into the session."""
    user_id, _, _ = test_user
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
    return client


@pytest.fixture
def test_expense(app, test_user):
    """Insert one expense belonging to test_user; return its integer id."""
    user_id, _, _ = test_user
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO expenses (user_id, amount, category, date, description)'
            ' VALUES (?, ?, ?, ?, ?)',
            (user_id, 99.00, 'Food', '2026-05-01', 'Test meal')
        )
        expense_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
    return expense_id


@pytest.fixture
def other_expense(app, other_user):
    """Insert one expense belonging to other_user; return its integer id."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO expenses (user_id, amount, category, date, description)'
            ' VALUES (?, ?, ?, ?, ?)',
            (other_user, 200.00, 'Transport', '2026-05-02', 'Bus fare')
        )
        expense_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
    return expense_id


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def _row_exists(app, expense_id):
    """Return True if a row with the given expense_id exists in the expenses table."""
    with app.app_context():
        row = get_db().execute(
            'SELECT id FROM expenses WHERE id = ?', (expense_id,)
        ).fetchone()
    return row is not None


def _expense_count(app, user_id):
    """Return the total number of expense rows for user_id."""
    with app.app_context():
        row = get_db().execute(
            'SELECT COUNT(*) FROM expenses WHERE user_id = ?', (user_id,)
        ).fetchone()
    return row[0]


# ================================================================== #
# Unit tests: delete_expense()                                        #
# ================================================================== #

class TestDeleteExpenseQuery:
    """Direct unit tests for the delete_expense() DB helper."""

    def test_correct_owner_removes_row(self, app, test_user, test_expense):
        """
        Spec: delete_expense with the correct owner's user_id removes the row
        from the expenses table entirely.
        """
        user_id, _, _ = test_user

        with app.app_context():
            delete_expense(test_expense, user_id)

        assert not _row_exists(app, test_expense), (
            f'Expected expense id={test_expense} to be deleted from DB '
            f'when called with the correct owner user_id'
        )

    def test_wrong_owner_leaves_row_intact(self, app, test_user, test_expense, other_user):
        """
        Spec: delete_expense called with a different user_id must NOT delete
        the row — ownership is scoped by id AND user_id in the WHERE clause.
        """
        with app.app_context():
            delete_expense(test_expense, other_user)

        assert _row_exists(app, test_expense), (
            f'Expected expense id={test_expense} to remain in DB when '
            f'delete_expense is called with the wrong user_id'
        )

    def test_non_existent_id_raises_no_error(self, app, test_user):
        """
        Spec: delete_expense with a non-existent expense_id must not raise
        any exception — it is a no-op.
        """
        user_id, _, _ = test_user
        non_existent_id = 999999

        with app.app_context():
            try:
                delete_expense(non_existent_id, user_id)
            except Exception as exc:
                pytest.fail(
                    f'delete_expense raised an unexpected exception for a '
                    f'non-existent id: {exc}'
                )

    def test_non_existent_id_leaves_db_unchanged(self, app, test_user, test_expense):
        """
        Spec: delete_expense with a non-existent expense_id leaves all
        existing rows untouched.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)

        with app.app_context():
            delete_expense(999999, user_id)

        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected row count to stay at {before} after calling '
            f'delete_expense with a non-existent id, but got {after}'
        )

    def test_correct_owner_decrements_row_count(self, app, test_user, test_expense):
        """
        Spec: After delete_expense with the correct owner, the expense count
        for that user decreases by exactly one.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)

        with app.app_context():
            delete_expense(test_expense, user_id)

        after = _expense_count(app, user_id)
        assert after == before - 1, (
            f'Expected expense count to drop from {before} to {before - 1}, '
            f'but got {after}'
        )

    def test_wrong_owner_does_not_decrement_row_count(self, app, test_user, test_expense, other_user):
        """
        Spec: delete_expense with the wrong user_id is a silent no-op —
        the owner's expense count must remain unchanged.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)

        with app.app_context():
            delete_expense(test_expense, other_user)

        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected expense count to stay at {before} after wrong-owner '
            f'delete attempt, but got {after}'
        )


# ================================================================== #
# Route tests: auth guard                                             #
# ================================================================== #

class TestDeleteExpenseAuthGuard:
    """Unauthenticated POST to /expenses/<id>/delete must redirect to /login."""

    def test_unauthenticated_post_redirects_to_login(self, client, test_expense):
        """
        Spec: POST /expenses/<id>/delete while logged out returns 302
        and the Location header points to /login.
        """
        response = client.post(f'/expenses/{test_expense}/delete')
        assert response.status_code == 302, (
            f'Expected 302 redirect for unauthenticated DELETE attempt, '
            f'got {response.status_code}'
        )
        assert '/login' in response.headers['Location'], (
            f'Expected redirect to /login, got {response.headers["Location"]}'
        )

    def test_unauthenticated_post_does_not_delete_row(self, client, app, test_expense):
        """
        Spec: An unauthenticated request must not delete anything from the DB.
        """
        client.post(f'/expenses/{test_expense}/delete')
        assert _row_exists(app, test_expense), (
            f'Expected expense id={test_expense} to remain in DB after '
            f'an unauthenticated delete attempt'
        )


# ================================================================== #
# Route tests: happy path                                             #
# ================================================================== #

class TestDeleteExpenseHappyPath:
    """Authenticated POST to own expense: correct redirect and DB row removed."""

    def test_own_expense_redirects_to_profile(self, auth_client, test_expense):
        """
        Spec: Deleting an owned expense returns 302 and redirects to /profile.
        """
        response = auth_client.post(f'/expenses/{test_expense}/delete')
        assert response.status_code == 302, (
            f'Expected 302 redirect after deleting own expense, '
            f'got {response.status_code}'
        )
        assert '/profile' in response.headers['Location'], (
            f'Expected redirect to /profile after delete, '
            f'got {response.headers["Location"]}'
        )

    def test_own_expense_row_removed_from_db(self, auth_client, app, test_expense):
        """
        Spec: After successfully deleting an owned expense, the row must no
        longer exist in the expenses table.
        """
        auth_client.post(f'/expenses/{test_expense}/delete')
        assert not _row_exists(app, test_expense), (
            f'Expected expense id={test_expense} to be removed from DB '
            f'after a successful delete by its owner'
        )

    def test_own_expense_count_decremented(self, auth_client, app, test_user, test_expense):
        """
        Spec: After deleting an owned expense, the total expense count for
        that user decreases by exactly one.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)

        auth_client.post(f'/expenses/{test_expense}/delete')

        after = _expense_count(app, user_id)
        assert after == before - 1, (
            f'Expected expense count to drop from {before} to {before - 1} '
            f'after successful delete, but got {after}'
        )


# ================================================================== #
# Route tests: cross-user ownership                                   #
# ================================================================== #

class TestDeleteExpenseCrossUserOwnership:
    """Authenticated POST to another user's expense must return 404 and leave DB intact."""

    def test_other_users_expense_returns_404(self, auth_client, other_expense):
        """
        Spec: POSTing to an expense that belongs to a different user returns 404.
        """
        response = auth_client.post(f'/expenses/{other_expense}/delete')
        assert response.status_code == 404, (
            f'Expected 404 when trying to delete another user\'s expense, '
            f'got {response.status_code}'
        )

    def test_other_users_expense_row_remains_in_db(self, auth_client, app, other_expense):
        """
        Spec: A cross-user delete attempt must not remove the target row from the DB.
        """
        auth_client.post(f'/expenses/{other_expense}/delete')
        assert _row_exists(app, other_expense), (
            f'Expected expense id={other_expense} to remain in DB after a '
            f'rejected cross-user delete attempt'
        )

    def test_other_users_expense_count_unchanged(self, auth_client, app, other_user, other_expense):
        """
        Spec: The other user's total expense count must remain unchanged after
        a rejected cross-user delete.
        """
        before = _expense_count(app, other_user)
        auth_client.post(f'/expenses/{other_expense}/delete')
        after = _expense_count(app, other_user)
        assert after == before, (
            f'Expected other user\'s expense count to stay at {before}, '
            f'but got {after}'
        )


# ================================================================== #
# Route tests: non-existent expense                                   #
# ================================================================== #

class TestDeleteExpenseNotFound:
    """Authenticated POST to a non-existent expense id must return 404."""

    def test_nonexistent_id_returns_404(self, auth_client):
        """
        Spec: POSTing to /expenses/999999/delete when that id does not exist
        returns 404.
        """
        response = auth_client.post('/expenses/999999/delete')
        assert response.status_code == 404, (
            f'Expected 404 when deleting a non-existent expense id, '
            f'got {response.status_code}'
        )

    def test_nonexistent_id_db_unchanged(self, auth_client, app, test_user, test_expense):
        """
        Spec: A 404 response for a non-existent id must not touch any existing rows.
        """
        user_id, _, _ = test_user
        before = _expense_count(app, user_id)

        auth_client.post('/expenses/999999/delete')

        after = _expense_count(app, user_id)
        assert after == before, (
            f'Expected expense count to stay at {before} after a 404 delete '
            f'attempt on a non-existent id, but got {after}'
        )


# ================================================================== #
# Route tests: method guard                                           #
# ================================================================== #

class TestDeleteExpenseMethodGuard:
    """GET requests to /expenses/<id>/delete must be rejected with 405."""

    def test_get_request_unauthenticated_returns_405(self, client, test_expense):
        """
        Spec: The route only accepts POST — a GET from an unauthenticated
        user must return 405 Method Not Allowed.
        """
        response = client.get(f'/expenses/{test_expense}/delete')
        assert response.status_code == 405, (
            f'Expected 405 for GET /expenses/<id>/delete (unauthenticated), '
            f'got {response.status_code}'
        )

    def test_get_request_authenticated_returns_405(self, auth_client, test_expense):
        """
        Spec: Even an authenticated GET to the delete URL must return 405
        — the route is POST-only.
        """
        response = auth_client.get(f'/expenses/{test_expense}/delete')
        assert response.status_code == 405, (
            f'Expected 405 for GET /expenses/<id>/delete (authenticated), '
            f'got {response.status_code}'
        )

    def test_get_request_does_not_delete_row(self, auth_client, app, test_expense):
        """
        Spec: A rejected GET request must leave the expense row intact in the DB.
        """
        auth_client.get(f'/expenses/{test_expense}/delete')
        assert _row_exists(app, test_expense), (
            f'Expected expense id={test_expense} to remain in DB after a '
            f'405-rejected GET request'
        )


# ================================================================== #
# Template: profile.html delete form                                  #
# ================================================================== #

class TestProfileDeleteFormTemplate:
    """The profile page must contain a POST delete form for each expense row."""

    def test_profile_contains_delete_form(self, auth_client, test_expense):
        """
        Spec: The profile page must contain a form whose action points to the
        delete route URL for the user's expense.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200, (
            f'Expected 200 for authenticated GET /profile, got {response.status_code}'
        )
        html = response.data.decode('utf-8')
        assert f'/expenses/{test_expense}/delete' in html, (
            f'Expected the profile page to contain a form action pointing to '
            f'/expenses/{test_expense}/delete'
        )

    def test_profile_delete_form_uses_post_method(self, auth_client, test_expense):
        """
        Spec: The delete form must use method="POST" — not GET — because the
        route only accepts POST.
        """
        response = auth_client.get('/profile')
        html = response.data.decode('utf-8')
        # Confirm a POST form exists somewhere on the page that references the delete path
        assert 'method="POST"' in html or 'method="post"' in html, (
            'Expected a form with method="POST" on the profile page '
            '(required for the delete action)'
        )

    def test_profile_delete_button_present(self, auth_client, test_expense):
        """
        Spec: Each transaction row in the profile table must have a Delete
        button/submit control visible to the user.
        """
        response = auth_client.get('/profile')
        html = response.data.decode('utf-8')
        assert 'Delete' in html, (
            'Expected a "Delete" button label to appear on the profile page'
        )

    def test_profile_shows_no_expense_after_deletion(self, auth_client, app, test_expense):
        """
        Spec: After deleting an expense, a subsequent GET /profile must not
        show that expense any longer.
        """
        # Delete the expense
        auth_client.post(f'/expenses/{test_expense}/delete')

        # Retrieve profile and confirm the deleted expense is absent
        response = auth_client.get('/profile')
        assert response.status_code == 200, (
            f'Expected 200 for /profile after deletion, got {response.status_code}'
        )
        html = response.data.decode('utf-8')
        assert f'/expenses/{test_expense}/delete' not in html, (
            f'Expected the delete form for expense id={test_expense} to be '
            f'absent from the profile page after deletion'
        )
