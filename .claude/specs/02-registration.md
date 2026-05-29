# Spec: Registration

## Overview
Implement user registration so new visitors can create a Spendly account.
The existing `GET /register` stub and `register.html` template are already in place;
this step adds the `POST /register` handler, a `create_user()` DB helper, server-side
validation, and a redirect to the login page on success also the user is shown a success message. It is the first feature that
writes user-supplied data to the database.

## Depends on
- Step 01 — Database Setup (`get_db()`, `users` table, werkzeug already installed)

## Routes
- `GET  /register` — render registration form — public (already exists, no change needed)
- `POST /register` — validate form data, insert user, redirect to login — public

## Database changes
No new tables or columns. One new helper function in `database/db.py`:

```python
def create_user(name, email, password_hash):
    """Insert a new user row. Returns the new user's id."""
```

The `users` table already has a `UNIQUE` constraint on `email`; duplicate emails will
raise `sqlite3.IntegrityError`, which the route must catch.

## Templates
- **Modify:** `templates/register.html`
  - Change `action="/register"` → `action="{{ url_for('register') }}"` (never hardcode URLs)
  - The `{% if error %}` block is already present — no further changes needed

## Files to change
- `app.py` — convert `register()` to handle both GET and POST; add `request` and
  `redirect` to Flask imports; add `create_user` to `database.db` import
- `database/db.py` — add `create_user()` helper
- `templates/register.html` — fix hardcoded action URL

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never f-strings in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash` before storing
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `create_user()` lives in `database/db.py`, not inline in the route
- On duplicate email, catch `sqlite3.IntegrityError` and re-render the form with
  `error="An account with that email already exists."`
- Validate in the route (not the DB helper): name non-empty, valid email format
  (trust the browser `type="email"` input — no regex needed server-side),
  password ≥ 8 characters
- On success: `redirect(url_for('login'))`
- On validation failure: `render_template('register.html', error=..., name=..., email=...)`
  so the user doesn't have to retype non-password fields

## Definition of done
- [ ] `POST /register` with valid data creates a new row in `users` with a hashed password
- [ ] Submitting a duplicate email re-renders the form with an error message (no crash)
- [ ] Submitting with mismatched passwords re-renders the form with an error message, no DB insert
- [ ] Submitting a password shorter than 8 characters re-renders the form with an error message
- [ ] Submitting an empty name re-renders the form with an error message
- [ ] Successful registration redirects to `/login`
- [ ] Previously entered name and email are preserved in the form on validation failure
- [ ] The form action uses `url_for('register')`, not a hardcoded string
- [ ] `app.py` has no inline SQL — all DB access goes through `database/db.py`
