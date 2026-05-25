from datetime import datetime

from database.db import get_db


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

def get_summary_stats(user_id):
    """Return dict {total_spent (str), transaction_count (int), top_category (str)}."""
    db = get_db()
    agg = db.execute(
        'SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt '
        'FROM expenses WHERE user_id = ?',
        (user_id,)
    ).fetchone()
    top = db.execute(
        'SELECT category FROM expenses WHERE user_id = ? '
        'GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1',
        (user_id,)
    ).fetchone()
    return {
        'total_spent': f"₹{agg['total']:,.0f}",
        'transaction_count': agg['cnt'],
        'top_category': top['category'] if top else '—',
    }


# ------------------------------------------------------------------ #
# Transaction history                                                 #
# ------------------------------------------------------------------ #

def get_recent_transactions(user_id, limit=10):
    """Return list of dicts ordered newest-first.
    Each dict: {date: 'DD Mon YYYY', description, category, amount: '₹X,XXX'}
    """
    rows = get_db().execute(
        'SELECT date, description, category, amount '
        'FROM expenses WHERE user_id = ? ORDER BY date DESC LIMIT ?',
        (user_id, limit)
    ).fetchall()
    result = []
    for row in rows:
        dt = datetime.strptime(row['date'], '%Y-%m-%d')
        result.append({
            'date': dt.strftime('%d %b %Y'),
            'description': row['description'] or '',
            'category': row['category'],
            'amount': f"₹{row['amount']:,.0f}",
        })
    return result


# ------------------------------------------------------------------ #
# Category breakdown                                                  #
# ------------------------------------------------------------------ #

def get_category_breakdown(user_id):
    """Return list of dicts [{name, amount: '₹X,XXX', pct: int}, ...] ordered by
    amount DESC. Integer pct values are adjusted so they sum to exactly 100.
    Returns [] when the user has no expenses.
    """
    rows = get_db().execute(
        'SELECT category, SUM(amount) AS cat_total '
        'FROM expenses WHERE user_id = ? '
        'GROUP BY category ORDER BY cat_total DESC',
        (user_id,)
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
