from datetime import datetime, date, timedelta

from database.db import get_db


# ------------------------------------------------------------------ #
# Date-filter helpers                                                 #
# ------------------------------------------------------------------ #

def _date_filter(date_from, date_to):
    """Return (clause_str, params_tuple) for an optional inclusive date range.

    Both date_from and date_to must be non-None ISO strings (YYYY-MM-DD) for
    the filter to activate.  When either is None, returns ('', ()) so the
    caller's WHERE clause is unchanged.
    """
    if date_from is not None and date_to is not None:
        return " AND date BETWEEN ? AND ?", (date_from, date_to)
    return "", ()


def build_date_presets(today=None):
    """Return a dict of named preset date ranges, each with date_from/date_to
    ISO strings.  Pass today as a date object to make the function testable
    without real-time dependency; defaults to date.today().
    """
    today = today or date.today()
    first_of_month = today.replace(day=1)
    return {
        "this_month": {
            "date_from": first_of_month.strftime("%Y-%m-%d"),
            "date_to":   today.strftime("%Y-%m-%d"),
        },
        "last_3_months": {
            "date_from": (today - timedelta(days=90)).strftime("%Y-%m-%d"),
            "date_to":   today.strftime("%Y-%m-%d"),
        },
        "last_6_months": {
            "date_from": (today - timedelta(days=180)).strftime("%Y-%m-%d"),
            "date_to":   today.strftime("%Y-%m-%d"),
        },
    }


def detect_active_preset(date_from_str, date_to_str, presets):
    """Return the key of the matching preset ('this_month', 'last_3_months',
    'last_6_months', 'all_time') or None when a custom range is active.
    """
    if date_from_str is None and date_to_str is None:
        return "all_time"
    for name, bounds in presets.items():
        if date_from_str == bounds["date_from"] and date_to_str == bounds["date_to"]:
            return name
    return None  # custom range


# ------------------------------------------------------------------ #
# User                                                                #
# ------------------------------------------------------------------ #

def get_user_by_id(user_id):
    """Return dict {name, email, member_since, initials} or None."""
    row = get_db().execute(
        'SELECT name, email, created_at FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()
    if row is None:
        return None
    dt = datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S')
    parts = row['name'].split()
    return {
        'name': row['name'],
        'email': row['email'],
        'member_since': dt.strftime('%B %Y'),
        'initials': ''.join(p[0].upper() for p in parts[:2]),
    }


# ------------------------------------------------------------------ #
# Summary stats                                                       #
# ------------------------------------------------------------------ #

def get_summary_stats(user_id, date_from=None, date_to=None):
    """Return dict {total_spent (str), transaction_count (int), top_category (str)}.

    When date_from and date_to are both provided (YYYY-MM-DD strings), only
    expenses within that inclusive range are included.
    """
    date_clause, date_params = _date_filter(date_from, date_to)
    db = get_db()
    agg = db.execute(
        'SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt '
        'FROM expenses WHERE user_id = ?' + date_clause,
        (user_id,) + date_params
    ).fetchone()
    top = db.execute(
        'SELECT category FROM expenses WHERE user_id = ?' + date_clause + ' '
        'GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1',
        (user_id,) + date_params
    ).fetchone()
    return {
        'total_spent': f"₹{agg['total']:,.0f}",
        'transaction_count': agg['cnt'],
        'top_category': top['category'] if top else '—',
    }


# ------------------------------------------------------------------ #
# Transaction history                                                 #
# ------------------------------------------------------------------ #

def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    """Return list of dicts ordered newest-first.
    Each dict: {id, date: 'DD Mon YYYY', description, category, amount: '₹X,XXX'}

    When date_from and date_to are both provided (YYYY-MM-DD strings), only
    expenses within that inclusive range are included.
    """
    date_clause, date_params = _date_filter(date_from, date_to)
    rows = get_db().execute(
        'SELECT id, date, description, category, amount '
        'FROM expenses WHERE user_id = ?' + date_clause +
        ' ORDER BY date DESC LIMIT ?',
        (user_id,) + date_params + (limit,)
    ).fetchall()
    result = []
    for row in rows:
        dt = datetime.strptime(row['date'], '%Y-%m-%d')
        result.append({
            'id': row['id'],
            'date': dt.strftime('%d %b %Y'),
            'description': row['description'] or '',
            'category': row['category'],
            'amount': f"₹{row['amount']:,.0f}",
        })
    return result


# ------------------------------------------------------------------ #
# Category breakdown                                                  #
# ------------------------------------------------------------------ #

def get_category_breakdown(user_id, date_from=None, date_to=None):
    """Return list of dicts [{name, amount: '₹X,XXX', pct: int}, ...] ordered by
    amount DESC. Integer pct values are adjusted so they sum to exactly 100.
    Returns [] when the user has no expenses.

    When date_from and date_to are both provided (YYYY-MM-DD strings), only
    expenses within that inclusive range are included.
    """
    date_clause, date_params = _date_filter(date_from, date_to)
    rows = get_db().execute(
        'SELECT category, SUM(amount) AS cat_total '
        'FROM expenses WHERE user_id = ?' + date_clause + ' '
        'GROUP BY category ORDER BY cat_total DESC',
        (user_id,) + date_params
    ).fetchall()
    if not rows:
        return []
    total = sum(r['cat_total'] for r in rows)
    result = [
        {
            'name': r['category'],
            '_raw': r['cat_total'],
            'pct': round(r['cat_total'] / total * 100),
        }
        for r in rows
    ]
    # Absorb rounding remainder into the largest category
    diff = 100 - sum(item['pct'] for item in result)
    result[0]['pct'] += diff
    for item in result:
        item['amount'] = f"₹{item['_raw']:,.0f}"
        del item['_raw']
    return result


# ------------------------------------------------------------------ #
# Expense mutations                                                   #
# ------------------------------------------------------------------ #

def get_expense_by_id(expense_id, user_id):
    """Return a single expense row as sqlite3.Row if it exists and belongs to user_id, else None."""
    return get_db().execute(
        'SELECT id, user_id, amount, category, date, description '
        'FROM expenses WHERE id = ? AND user_id = ?',
        (expense_id, user_id)
    ).fetchone()


def update_expense(expense_id, user_id, amount, category, expense_date, description):
    """Update an existing expense row. Scoped to user_id to prevent cross-user edits."""
    db = get_db()
    db.execute(
        'UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? '
        'WHERE id = ? AND user_id = ?',
        (amount, category, expense_date, description, expense_id, user_id)
    )
    db.commit()


def insert_expense(user_id, amount, category, expense_date, description):
    """Insert a new expense row and commit.

    Args:
        user_id (int): FK to users.id
        amount (float): positive monetary value
        category (str): one of the fixed VALID_CATEGORIES
        expense_date (str): ISO date string YYYY-MM-DD
        description (str | None): optional free-text note
    """
    db = get_db()
    db.execute(
        'INSERT INTO expenses (user_id, amount, category, date, description)'
        ' VALUES (?, ?, ?, ?, ?)',
        (user_id, amount, category, expense_date, description)
    )
    db.commit()
