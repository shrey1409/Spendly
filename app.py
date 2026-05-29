import os
import math
import sqlite3
from datetime import datetime
from flask import Flask, render_template, g, request, redirect, url_for, session, abort, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import init_db, seed_db, create_user, get_user_by_email
from database.queries import (
    get_user_by_id, get_summary_stats,
    get_recent_transactions, get_category_breakdown,
    build_date_presets, detect_active_preset,
    insert_expense, get_expense_by_id, update_expense,
    delete_expense as _delete_expense,
)

VALID_CATEGORIES = ['Food', 'Transport', 'Bills', 'Health',
                    'Entertainment', 'Shopping', 'Other']

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "spendly-dev-secret")
app.config['DATABASE'] = 'database/spendly.db'


@app.teardown_appcontext
def close_db(_exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name:
        return render_template("register.html", error="Name is required.", name=name, email=email)
    if len(password) < 8:
        return render_template("register.html", error="Password must be at least 8 characters.", name=name, email=email)
    if password != confirm_password:
        return render_template("register.html", error="Passwords do not match.", name=name, email=email)

    try:
        create_user(name, email, generate_password_hash(password, method="pbkdf2:sha256"))
    except sqlite3.IntegrityError:
        return render_template("register.html", error="An account with that email already exists.", name=name, email=email)

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    user = get_user_by_email(email)
    if user and check_password_hash(user["password_hash"], password):
        session["user_id"] = user["id"]
        return redirect(url_for("profile"))

    return render_template("login.html", error="Invalid email or password.", email=email)


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    user = get_user_by_id(uid)
    if user is None:
        abort(404)

    # ------------------------------------------------------------------ #
    # 1. Extract raw query params                                         #
    # ------------------------------------------------------------------ #
    raw_from = request.args.get("date_from", "").strip()
    raw_to   = request.args.get("date_to",   "").strip()

    # ------------------------------------------------------------------ #
    # 2. Validate: attempt ISO parse; silently discard malformed values   #
    # ------------------------------------------------------------------ #
    date_from = None
    date_to   = None

    try:
        if raw_from:
            date_from = datetime.strptime(raw_from, "%Y-%m-%d").date()
    except ValueError:
        pass  # malformed — treat as absent

    try:
        if raw_to:
            date_to = datetime.strptime(raw_to, "%Y-%m-%d").date()
    except ValueError:
        pass  # malformed — treat as absent

    # ------------------------------------------------------------------ #
    # 3. Logical validation                                               #
    # ------------------------------------------------------------------ #
    if date_from is not None and date_to is not None and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = None
        date_to   = None
    elif (date_from is None) != (date_to is None):
        # Exactly one bound provided — filter would silently do nothing
        flash("Please provide both a start date and an end date to filter.", "error")
        date_from = None
        date_to   = None

    # ------------------------------------------------------------------ #
    # 4. Convert validated date objects → ISO strings for SQL             #
    # ------------------------------------------------------------------ #
    date_from_str = date_from.strftime("%Y-%m-%d") if date_from else None
    date_to_str   = date_to.strftime("%Y-%m-%d")   if date_to   else None

    # ------------------------------------------------------------------ #
    # 5. Preset date ranges and active-preset detection (via helpers)     #
    # ------------------------------------------------------------------ #
    presets       = build_date_presets()
    active_preset = detect_active_preset(date_from_str, date_to_str, presets)

    # ------------------------------------------------------------------ #
    # 6. Query with (possibly filtered) params                            #
    # ------------------------------------------------------------------ #
    stats        = get_summary_stats(uid, date_from=date_from_str, date_to=date_to_str)
    transactions = get_recent_transactions(uid, date_from=date_from_str, date_to=date_to_str)
    categories   = get_category_breakdown(uid, date_from=date_from_str, date_to=date_to_str)

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        date_from=date_from_str,
        date_to=date_to_str,
        presets=presets,
        active_preset=active_preset,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        today = datetime.now().strftime("%Y-%m-%d")
        return render_template("add_expense.html",
                               categories=VALID_CATEGORIES, today=today)

    # --- POST ---
    raw_amount  = request.form.get("amount", "").strip()
    category    = request.form.get("category", "").strip()
    raw_date    = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    if description and len(description) > 200:
        description = description[:200]

    form_values = dict(amount=raw_amount, category=category,
                       date=raw_date, description=description)

    def rerender(error):
        return render_template("add_expense.html",
                               categories=VALID_CATEGORIES,
                               error=error,
                               **form_values)

    try:
        amount = float(raw_amount)
        if amount <= 0 or math.isinf(amount) or math.isnan(amount):
            raise ValueError
    except ValueError:
        return rerender("Amount must be a positive number greater than 0.")

    if category not in VALID_CATEGORIES:
        return rerender("Please select a valid category.")

    try:
        datetime.strptime(raw_date, "%Y-%m-%d")
    except ValueError:
        return rerender("Please enter a valid date (YYYY-MM-DD).")

    insert_expense(session["user_id"], amount, category, raw_date, description)
    flash("Expense added successfully!", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    expense = get_expense_by_id(id, uid)
    if expense is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            categories=VALID_CATEGORIES,
            expense_id=id,
            amount=expense["amount"],
            category=expense["category"],
            date=expense["date"],
            description=expense["description"] or "",
        )

    # --- POST ---
    raw_amount  = request.form.get("amount", "").strip()
    category    = request.form.get("category", "").strip()
    raw_date    = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    if description and len(description) > 200:
        description = description[:200]

    def rerender(error):
        return render_template(
            "edit_expense.html",
            categories=VALID_CATEGORIES,
            expense_id=id,
            error=error,
            amount=raw_amount,
            category=category,
            date=raw_date,
            description=description,
        )

    try:
        amount = float(raw_amount)
        if amount <= 0 or math.isinf(amount) or math.isnan(amount):
            raise ValueError
    except ValueError:
        return rerender("Amount must be a positive number greater than 0.")

    if category not in VALID_CATEGORIES:
        return rerender("Please select a valid category.")

    try:
        datetime.strptime(raw_date, "%Y-%m-%d")
    except ValueError:
        return rerender("Please enter a valid date (YYYY-MM-DD).")

    update_expense(id, uid, amount, category, raw_date, description)
    flash("Expense updated successfully!", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    uid = session["user_id"]
    if get_expense_by_id(id, uid) is None:
        abort(404)
    _delete_expense(id, uid)
    flash("Expense deleted.", "success")
    return redirect(url_for("profile"))


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, port=5001)
