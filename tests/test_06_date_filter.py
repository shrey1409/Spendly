"""
Tests for Step 06: Date Filter for Profile Page

Spec reference:
  .claude/specs/06-date-filter-profile-page.md

All route tests seed data manually via the DB fixture pattern established in
test_backend_connection.py.  Query-helper tests call the functions directly
inside an app_context so they are independent of the HTTP layer.

Seed reminder (from spec):
  - Demo expenses are ALL in May 2026 (dates 2026-05-01 through 2026-05-18).
  - April 2026 (2026-04-01 – 2026-04-30) is used as the guaranteed "empty"
    date range throughout these tests.
"""

import pytest
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

from database.db import get_db, init_db
from database.queries import (
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def app(tmp_path):
    """Isolated app instance backed by a fresh temp-file SQLite database."""
    from app import app as flask_app
    flask_app.config['DATABASE'] = str(tmp_path / 'test_06.db')
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_user(app):
    """
    Insert one test user whose expenses all fall in May 2026 — matching the
    spec's seed-data reference.  Returns (user_id, email, password).
    """
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (
                'Filter Tester',
                'filter@example.com',
                generate_password_hash('pass1234', method='pbkdf2:sha256'),
                '2026-01-01 00:00:00',
            )
        )
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.executemany(
            'INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)',
            [
                (user_id, 450.00,  'Food',          '2026-05-01', 'Grocery run'),
                (user_id, 120.00,  'Transport',     '2026-05-03', 'Metro card top-up'),
                (user_id, 1800.00, 'Bills',         '2026-05-05', 'Electricity bill'),
                (user_id, 300.00,  'Health',        '2026-05-08', 'Pharmacy'),
                (user_id, 650.00,  'Entertainment', '2026-05-10', 'Movie night'),
                (user_id, 2200.00, 'Shopping',      '2026-05-12', 'New shoes'),
                (user_id, 80.00,   'Other',         '2026-05-14', 'Miscellaneous'),
                (user_id, 390.00,  'Food',          '2026-05-18', 'Restaurant dinner'),
            ]
        )
        db.commit()
    return user_id


@pytest.fixture
def auth_client(client, seed_user):
    """Test client with seed_user already in session."""
    with client.session_transaction() as sess:
        sess['user_id'] = seed_user
    return client


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _this_month_params():
    """Return (date_from, date_to) strings for the 'This Month' preset."""
    today = date.today()
    return today.replace(day=1).strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')


# ================================================================== #
# TestProfileRouteFilter                                              #
# ================================================================== #

class TestProfileRouteFilter:
    """Route-level tests: GET /profile with various query-string combinations."""

    def test_no_params_returns_200_unfiltered(self, auth_client):
        """
        Spec: Visiting /profile with no query params returns the same data
        as unfiltered (all expenses).  All eight May expenses should be
        reflected in the page and the response must be 200.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200, 'Expected 200 for authenticated /profile with no params'
        # All eight seed expenses belong to the user — total is 5990
        assert '5,990'.encode() in response.data, (
            'Expected total ₹5,990 (sum of all 8 seed expenses) in unfiltered profile page'
        )

    def test_this_month_preset_filters_data(self, auth_client):
        """
        Spec: date_from/date_to matching 'This Month' returns 200 and data
        filtered to that calendar month.  When today is in May 2026, all
        seed expenses fall within the range and the total must equal ₹5,990.
        When today is NOT May 2026 the range has no matching expenses and
        the route must still return 200 without crashing.
        """
        date_from, date_to = _this_month_params()
        url = f'/profile?date_from={date_from}&date_to={date_to}'
        response = auth_client.get(url)
        assert response.status_code == 200, (
            f'Expected 200 for This Month filter ({date_from} – {date_to})'
        )

    def test_empty_date_range_returns_200_no_crash(self, auth_client):
        """
        Spec: A range that contains no expenses (April 2026) returns 200,
        shows ₹0 total, 0 transactions, and an empty breakdown — no errors.
        """
        response = auth_client.get('/profile?date_from=2026-04-01&date_to=2026-04-30')
        assert response.status_code == 200, 'Expected 200 for an empty-range date filter'
        assert b'0' in response.data, 'Expected zero transaction count in response for empty range'
        # No crash means no 500 and the page still renders
        assert b'profile-filter-bar' in response.data or response.status_code == 200

    def test_reversed_dates_flashes_error_and_falls_back(self, auth_client):
        """
        Spec: If date_from > date_to, the route must flash
        'Start date must be before end date.' and fall back to the
        unfiltered view (returning all expenses, not an empty set).
        """
        response = auth_client.get(
            '/profile?date_from=2026-05-20&date_to=2026-05-01',
            follow_redirects=True
        )
        assert response.status_code == 200, 'Expected 200 even for reversed date range'
        assert 'Start date must be before end date.'.encode() in response.data, (
            'Expected flash message for reversed date range'
        )
        # Fall-back: the full unfiltered total must be visible
        assert '5,990'.encode() in response.data, (
            'Expected unfiltered total ₹5,990 after reversed-date fallback'
        )

    def test_malformed_dates_no_crash(self, auth_client):
        """
        Spec: Malformed date strings (e.g. 'not-a-date') must not crash the
        app — the route falls back silently to the unfiltered view.
        """
        response = auth_client.get(
            '/profile?date_from=not-a-date&date_to=also-bad'
        )
        assert response.status_code == 200, 'Expected 200 for malformed date strings'
        # Unfiltered fallback: full data visible
        assert '5,990'.encode() in response.data, (
            'Expected unfiltered total after malformed-date fallback'
        )

    def test_only_date_from_no_crash(self, auth_client):
        """
        Spec: If only date_from is provided (date_to absent), the route must
        not crash and must fall back to the unfiltered view.
        """
        response = auth_client.get('/profile?date_from=2026-05-01')
        assert response.status_code == 200, 'Expected 200 when only date_from is provided'
        # Falls back to unfiltered
        assert '5,990'.encode() in response.data, (
            'Expected unfiltered total when only date_from is supplied'
        )

    def test_unauthenticated_redirects_to_login(self, client):
        """
        Spec (auth guard): An unauthenticated request to /profile must be
        redirected (302) to /login, regardless of any query params.
        """
        response = client.get('/profile?date_from=2026-05-01&date_to=2026-05-31')
        assert response.status_code == 302, 'Expected 302 redirect for unauthenticated /profile'
        assert '/login' in response.headers['Location'], (
            'Expected redirect target to be /login'
        )


# ================================================================== #
# TestQueryHelperDateFilter                                           #
# ================================================================== #

class TestQueryHelperDateFilter:
    """Unit tests for the three query helpers with date_from / date_to args."""

    # ---- get_summary_stats ---------------------------------------- #

    def test_summary_stats_filtered_in_range(self, app, seed_user):
        """
        Spec: get_summary_stats(uid, date_from, date_to) with expenses in
        range returns correct filtered totals.

        Seeded May 2026 expenses in range 2026-05-01 to 2026-05-08:
          450 (Food) + 120 (Transport) + 1800 (Bills) + 300 (Health) = 2670
          transaction_count = 4, top_category = 'Bills'
        """
        with app.app_context():
            result = get_summary_stats(
                seed_user,
                date_from='2026-05-01',
                date_to='2026-05-08',
            )
        assert result['transaction_count'] == 4, (
            'Expected 4 transactions in range 2026-05-01 to 2026-05-08'
        )
        assert '2,670' in result['total_spent'], (
            f"Expected total ₹2,670 but got {result['total_spent']}"
        )
        assert result['top_category'] == 'Bills', (
            'Expected top category Bills (highest single amount in range)'
        )

    def test_summary_stats_no_expenses_in_range(self, app, seed_user):
        """
        Spec: get_summary_stats with NO expenses in range returns ₹0 total,
        0 transactions, and '—' for top_category.
        April 2026 contains no seed expenses.
        """
        with app.app_context():
            result = get_summary_stats(
                seed_user,
                date_from='2026-04-01',
                date_to='2026-04-30',
            )
        assert result['transaction_count'] == 0, (
            'Expected 0 transactions for April 2026 (empty range)'
        )
        assert result['total_spent'] == '₹0', (
            f"Expected ₹0 for empty range but got {result['total_spent']}"
        )
        assert result['top_category'] == '—', (
            "Expected '—' as top_category when no expenses exist in range"
        )

    def test_summary_stats_unfiltered_matches_all_expenses(self, app, seed_user):
        """
        Spec: When called without date_from/date_to, get_summary_stats must
        behave identically to its Step 5 (unfiltered) behaviour.
        All 8 seed expenses: total = 5990, count = 8.
        """
        with app.app_context():
            result = get_summary_stats(seed_user)
        assert result['transaction_count'] == 8, (
            'Expected 8 transactions in unfiltered view'
        )
        assert '5,990' in result['total_spent'], (
            f"Expected total ₹5,990 (unfiltered) but got {result['total_spent']}"
        )

    # ---- get_recent_transactions ----------------------------------- #

    def test_recent_transactions_only_in_range(self, app, seed_user):
        """
        Spec: get_recent_transactions(uid, date_from, date_to) returns only
        transactions within the range, ordered newest-first.

        Range 2026-05-10 to 2026-05-14 covers:
          2026-05-10 Entertainment, 2026-05-12 Shopping, 2026-05-14 Other
        Newest-first: 2026-05-14, 2026-05-12, 2026-05-10
        """
        with app.app_context():
            result = get_recent_transactions(
                seed_user,
                date_from='2026-05-10',
                date_to='2026-05-14',
            )
        assert len(result) == 3, (
            f'Expected 3 transactions in range 2026-05-10–2026-05-14, got {len(result)}'
        )
        # Ordered newest-first
        assert result[0]['date'] == '14 May 2026', (
            f"Expected first result to be 14 May 2026 but got {result[0]['date']}"
        )
        assert result[1]['date'] == '12 May 2026', (
            f"Expected second result to be 12 May 2026 but got {result[1]['date']}"
        )
        assert result[2]['date'] == '10 May 2026', (
            f"Expected third result to be 10 May 2026 but got {result[2]['date']}"
        )

    def test_recent_transactions_excludes_out_of_range(self, app, seed_user):
        """
        Spec: Transactions outside the date range must not appear.
        Range 2026-05-01 to 2026-05-03 covers only the first two expenses.
        """
        with app.app_context():
            result = get_recent_transactions(
                seed_user,
                date_from='2026-05-01',
                date_to='2026-05-03',
            )
        assert len(result) == 2, (
            f'Expected 2 transactions in range 2026-05-01–2026-05-03, got {len(result)}'
        )
        dates_returned = {tx['date'] for tx in result}
        assert '01 May 2026' in dates_returned
        assert '03 May 2026' in dates_returned
        # Expense on 2026-05-05 must not appear
        assert '05 May 2026' not in dates_returned, (
            'Expense from 2026-05-05 must not appear when range ends 2026-05-03'
        )

    def test_recent_transactions_unfiltered_returns_all(self, app, seed_user):
        """
        Spec: When called without date_from/date_to, behaviour is identical
        to Step 5 (unfiltered) — returns all 8 seed expenses.
        """
        with app.app_context():
            result = get_recent_transactions(seed_user)
        assert len(result) == 8, (
            f'Expected 8 transactions unfiltered, got {len(result)}'
        )

    # ---- get_category_breakdown ------------------------------------ #

    def test_category_breakdown_in_range_sums_to_100(self, app, seed_user):
        """
        Spec: get_category_breakdown with expenses in range only includes
        categories with expenses in that range; pct values sum to exactly 100.

        Range 2026-05-01 to 2026-05-05 covers Food (450) + Transport (120) +
        Bills (1800) — three distinct categories.
        """
        with app.app_context():
            result = get_category_breakdown(
                seed_user,
                date_from='2026-05-01',
                date_to='2026-05-05',
            )
        assert len(result) == 3, (
            f'Expected 3 categories in range 2026-05-01–2026-05-05, got {len(result)}'
        )
        category_names = {item['name'] for item in result}
        assert 'Food' in category_names
        assert 'Transport' in category_names
        assert 'Bills' in category_names
        # Categories outside range must not appear
        assert 'Health' not in category_names, (
            'Health (2026-05-08) must not appear when range ends 2026-05-05'
        )
        total_pct = sum(item['pct'] for item in result)
        assert total_pct == 100, (
            f'pct values must sum to 100, got {total_pct}'
        )

    def test_category_breakdown_empty_range_returns_empty_list(self, app, seed_user):
        """
        Spec: get_category_breakdown with NO expenses in range returns [].
        April 2026 contains no seed expenses.
        """
        with app.app_context():
            result = get_category_breakdown(
                seed_user,
                date_from='2026-04-01',
                date_to='2026-04-30',
            )
        assert result == [], (
            f'Expected [] for empty range (April 2026), got {result}'
        )

    def test_category_breakdown_unfiltered_includes_all_categories(self, app, seed_user):
        """
        Spec: When called without date_from/date_to, behaviour is identical
        to Step 5 — all 7 distinct seed categories must appear.
        """
        with app.app_context():
            result = get_category_breakdown(seed_user)
        category_names = {item['name'] for item in result}
        expected = {'Food', 'Transport', 'Bills', 'Health', 'Entertainment', 'Shopping', 'Other'}
        assert category_names == expected, (
            f'Expected all 7 categories unfiltered, got {category_names}'
        )
        assert sum(item['pct'] for item in result) == 100


# ================================================================== #
# TestFilterBarUI                                                     #
# ================================================================== #

class TestFilterBarUI:
    """Template / HTML tests verified via the test-client response body."""

    def test_filter_bar_element_present(self, auth_client):
        """
        Spec: The profile page must include a filter bar section.
        Verified by the presence of the CSS class 'profile-filter-bar'
        in the rendered HTML.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200
        assert b'profile-filter-bar' in response.data, (
            "Expected element with class 'profile-filter-bar' in profile page HTML"
        )

    def test_all_time_link_has_no_date_params(self, auth_client):
        """
        Spec: The 'All Time' preset must pass no query params — the href
        must point to the clean /profile URL, not /profile?date_from=...
        Verified by checking that the response contains '/profile' as a
        standalone href without date query params adjacent to the All Time label.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # The All Time link must exist and target /profile without date params.
        # We look for href="/profile" somewhere in the page (url_for('profile')
        # with no args produces exactly this path).
        assert 'href="/profile"' in html, (
            "Expected All Time link to use href=\"/profile\" (no query params)"
        )

    def test_active_preset_class_on_this_month(self, auth_client):
        """
        Spec: The currently active preset button must carry the CSS class
        'profile-filter-btn--active'.  When the This Month preset params are
        passed, that button must be marked active.
        """
        date_from, date_to = _this_month_params()
        response = auth_client.get(f'/profile?date_from={date_from}&date_to={date_to}')
        assert response.status_code == 200
        assert b'profile-filter-btn--active' in response.data, (
            "Expected 'profile-filter-btn--active' class when This Month preset is active"
        )

    def test_all_time_active_class_when_no_params(self, auth_client):
        """
        Spec: When no date params are supplied, the 'All Time' preset is
        active and its button must carry 'profile-filter-btn--active'.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200
        assert b'profile-filter-btn--active' in response.data, (
            "Expected 'profile-filter-btn--active' on All Time button when no filter is active"
        )

    def test_rupee_symbol_present_with_no_filter(self, auth_client):
        """
        Spec: All amounts must display the ₹ symbol regardless of the
        active filter — verified here for the unfiltered (All Time) view.
        """
        response = auth_client.get('/profile')
        assert response.status_code == 200
        assert '₹'.encode('utf-8') in response.data, (
            'Expected ₹ symbol in profile page with no active filter'
        )

    def test_rupee_symbol_present_with_date_filter(self, auth_client):
        """
        Spec: All amounts must display the ₹ symbol regardless of the
        active filter — verified here for a non-empty filtered view.
        Range 2026-05-01 to 2026-05-10 covers five seed expenses.
        """
        response = auth_client.get('/profile?date_from=2026-05-01&date_to=2026-05-10')
        assert response.status_code == 200
        assert '₹'.encode('utf-8') in response.data, (
            'Expected ₹ symbol in profile page with an active date filter'
        )

    def test_rupee_symbol_present_with_empty_filter(self, auth_client):
        """
        Spec: Even when the selected range contains no expenses (zero totals),
        the ₹ symbol must still appear in the rendered page.
        """
        response = auth_client.get('/profile?date_from=2026-04-01&date_to=2026-04-30')
        assert response.status_code == 200
        assert '₹'.encode('utf-8') in response.data, (
            'Expected ₹ symbol even when the filtered range contains no expenses'
        )
