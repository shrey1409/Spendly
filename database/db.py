import sqlite3
from flask import g, current_app
from werkzeug.security import generate_password_hash


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES                                                                                                                                                                                                   
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    ''')
    db.commit()


def seed_db():
    db = get_db()
    if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0:
        return

    db.execute(
        'INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
        ('Demo User', 'demo@spendly.com', generate_password_hash('demo123'))
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
