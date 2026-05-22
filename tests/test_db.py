import sqlite3
import pytest
from database.db import get_db, init_db, seed_db


def test_init_db_creates_tables(app):
    with app.app_context():
        db = get_db()
        tables = {row['name'] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert 'users' in tables
        assert 'expenses' in tables


def test_init_db_is_idempotent(app):
    with app.app_context():
        init_db()
        init_db()


def test_get_db_returns_row_factory_connection(app):
    with app.app_context():
        db = get_db()
        db.execute(
            'INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
            ('Test', 'test@example.com', 'hash')
        )
        db.commit()
        row = db.execute(
            'SELECT * FROM users WHERE email = ?', ('test@example.com',)
        ).fetchone()
        assert row['email'] == 'test@example.com'


def test_get_db_returns_same_connection_within_context(app):
    with app.app_context():
        db1 = get_db()
        db2 = get_db()
        assert db1 is db2


def test_get_db_foreign_keys_enforced(app):
    with app.app_context():
        db = get_db()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                'INSERT INTO expenses (user_id, amount, category, date) VALUES (?, ?, ?, ?)',
                (9999, 100.0, 'Food', '2026-05-01')
            )
            db.commit()


def test_seed_db_inserts_demo_data(app):
    with app.app_context():
        seed_db()
        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE email = ?', ('demo@spendly.com',)
        ).fetchone()
        assert user is not None
        assert user['name'] == 'Demo User'
        count = db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0]
        assert count == 8


def test_seed_db_is_idempotent(app):
    with app.app_context():
        seed_db()
        seed_db()
        db = get_db()
        count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        assert count == 1
