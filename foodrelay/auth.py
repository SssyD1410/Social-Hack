from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, query
from .helpers import ROLES

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_logged_in_user():
    uid = session.get("user_id")
    g.user = query("SELECT * FROM users WHERE id = ?", (uid,), one=True) if uid else None


@bp.route("/register", methods=("GET", "POST"))
def register():
    role = request.values.get("role", "")
    if request.method == "POST":
        f = request.form
        email = f.get("email", "").strip().lower()
        name = f.get("name", "").strip()
        password = f.get("password", "")
        errors = []
        if role not in ROLES:
            errors.append("Choose an account type.")
        if not name:
            errors.append("Name is required.")
        if "@" not in email:
            errors.append("Enter a valid email.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != f.get("confirm", ""):
            errors.append("Passwords don't match.")
        if role in ("supplier", "distributor") and not f.get("org_name", "").strip():
            errors.append("Organization / business name is required.")
        if not errors and query("SELECT 1 FROM users WHERE email = ?", (email,), one=True):
            errors.append("An account with that email already exists.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            uid = execute(
                """INSERT INTO users (email, password_hash, name, role, org_name, phone, city, address,
                                      verification_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (email, generate_password_hash(password), name, role,
                 f.get("org_name", "").strip() or None, f.get("phone", "").strip() or None,
                 f.get("city", "").strip() or None, f.get("address", "").strip() or None,
                 "unverified" if role == "distributor" else "not_required"))
            session.clear()
            session["user_id"] = uid
            flash(f"Welcome to FoodRelay, {name}!", "success")
            if role == "distributor":
                flash("Next step: upload your certification so we can verify your organization.", "info")
                return redirect(url_for("main.profile"))
            return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html", role=role)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            flash("Incorrect email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            # Only follow local redirects.
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("main.dashboard"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))
