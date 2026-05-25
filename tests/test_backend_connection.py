import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app
from database.db import get_db, init_db
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def app(tmp_path):
    flask_app.config['DATABASE'] = str(tmp_path / 'test.db')
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_user(app):
    """Insert one test user + 3 expenses. Returns user_id."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            ('Test User', 'test@example.com',
             generate_password_hash('password123', method='pbkdf2:sha256'), '2026-01-15 10:00:00')
        )
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.executemany(
            'INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)',
            [
                (user_id, 500.00, 'Food',          '2026-05-10', 'Lunch'),
                (user_id, 200.00, 'Transport',     '2026-05-08', 'Taxi'),
                (user_id, 300.00, 'Food',          '2026-05-05', 'Dinner'),
            ]
        )
        db.commit()
    return user_id


@pytest.fixture
def empty_user(app):
    """Insert one test user with no expenses. Returns user_id."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            ('Empty User', 'empty@example.com',
             generate_password_hash('password123', method='pbkdf2:sha256'), '2026-03-01 09:00:00')
        )
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
    return user_id


# ------------------------------------------------------------------ #
# get_user_by_id                                                      #
# ------------------------------------------------------------------ #

def test_get_user_by_id_valid(app, seed_user):
    with app.app_context():
        result = get_user_by_id(seed_user)
    assert result is not None
    assert result['name'] == 'Test User'
    assert result['email'] == 'test@example.com'
    assert result['member_since'] == 'January 2026'
    assert result['initials'] == 'TU'


def test_get_user_by_id_missing(app):
    with app.app_context():
        result = get_user_by_id(99999)
    assert result is None


def test_get_user_by_id_single_name(app):
    """User with one word name gets a single initial."""
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            ('Madonna', 'madonna@example.com', 'hash', '2026-02-10 08:00:00')
        )
        uid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
        result = get_user_by_id(uid)
    assert result['initials'] == 'M'


# ------------------------------------------------------------------ #
# get_summary_stats                                                   #
# ------------------------------------------------------------------ #

def test_get_summary_stats_with_expenses(app, seed_user):
    with app.app_context():
        result = get_summary_stats(seed_user)
    assert result['transaction_count'] == 3
    assert result['total_spent'] == '₹1,000'   # 500 + 200 + 300
    assert result['top_category'] == 'Food'    # Food total = 800


def test_get_summary_stats_no_expenses(app, empty_user):
    with app.app_context():
        result = get_summary_stats(empty_user)
    assert result['transaction_count'] == 0
    assert result['total_spent'] == '₹0'
    assert result['top_category'] == '—'


# ------------------------------------------------------------------ #
# get_recent_transactions                                             #
# ------------------------------------------------------------------ #

def test_get_recent_transactions_with_expenses(app, seed_user):
    with app.app_context():
        result = get_recent_transactions(seed_user)
    assert len(result) == 3
    # Ordered newest-first: 2026-05-10, 2026-05-08, 2026-05-05
    assert result[0]['date'] == '10 May 2026'
    assert result[1]['date'] == '08 May 2026'
    assert result[2]['date'] == '05 May 2026'
    # Check all required keys exist
    for tx in result:
        assert 'date' in tx
        assert 'description' in tx
        assert 'category' in tx
        assert 'amount' in tx
        assert tx['amount'].startswith('₹')


def test_get_recent_transactions_no_expenses(app, empty_user):
    with app.app_context():
        result = get_recent_transactions(empty_user)
    assert result == []


def test_get_recent_transactions_limit(app, seed_user):
    with app.app_context():
        result = get_recent_transactions(seed_user, limit=2)
    assert len(result) == 2


def test_get_recent_transactions_amount_format(app, seed_user):
    with app.app_context():
        result = get_recent_transactions(seed_user)
    amounts = [tx['amount'] for tx in result]
    assert '₹500' in amounts
    assert '₹200' in amounts
    assert '₹300' in amounts


# ------------------------------------------------------------------ #
# get_category_breakdown                                              #
# ------------------------------------------------------------------ #

def test_get_category_breakdown_with_expenses(app, seed_user):
    with app.app_context():
        result = get_category_breakdown(seed_user)
    assert len(result) == 2  # Food and Transport
    # Ordered by amount DESC: Food (800) then Transport (200)
    assert result[0]['name'] == 'Food'
    assert result[1]['name'] == 'Transport'
    # pct values are integers summing to 100
    total_pct = sum(item['pct'] for item in result)
    assert total_pct == 100
    for item in result:
        assert isinstance(item['pct'], int)
        assert item['amount'].startswith('₹')


def test_get_category_breakdown_no_expenses(app, empty_user):
    with app.app_context():
        result = get_category_breakdown(empty_user)
    assert result == []


def test_get_category_breakdown_pct_sum(app, seed_user):
    """pct values must always sum to exactly 100."""
    with app.app_context():
        result = get_category_breakdown(seed_user)
    assert sum(item['pct'] for item in result) == 100


# ------------------------------------------------------------------ #
# Route tests — GET /profile                                          #
# ------------------------------------------------------------------ #

def test_profile_unauthenticated_redirects(client):
    response = client.get('/profile')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_profile_authenticated_returns_200(client, app, seed_user):
    with client.session_transaction() as sess:
        sess['user_id'] = seed_user
    response = client.get('/profile')
    assert response.status_code == 200


def test_profile_shows_real_user_name(client, app, seed_user):
    with client.session_transaction() as sess:
        sess['user_id'] = seed_user
    response = client.get('/profile')
    assert b'Test User' in response.data


def test_profile_shows_real_email(client, app, seed_user):
    with client.session_transaction() as sess:
        sess['user_id'] = seed_user
    response = client.get('/profile')
    assert b'test@example.com' in response.data


def test_profile_shows_rupee_symbol(client, app, seed_user):
    with client.session_transaction() as sess:
        sess['user_id'] = seed_user
    response = client.get('/profile')
    assert '₹'.encode() in response.data


def test_profile_empty_user_no_errors(client, app, empty_user):
    with client.session_transaction() as sess:
        sess['user_id'] = empty_user
    response = client.get('/profile')
    assert response.status_code == 200
