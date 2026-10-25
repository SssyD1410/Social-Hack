from urllib.parse import urlsplit

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, query
from .helpers import ROLES, client_ip, over_limit, parse_latlng, record_attempt

bp = Blueprint("auth", __name__)

# Compared against when an email has no account, so a failed login takes as long either way
# (otherwise the response time would reveal which emails are registered).
_DUMMY_HASH = generate_password_hash("not-a-real-password")

LOGIN_LIMIT = (5, 15 * 60)        # failed logins per email, per 15 minutes
LOGIN_IP_LIMIT = (30, 15 * 60)    # failed logins per IP address, per 15 minutes
REGISTER_LIMIT = (10, 60 * 60)    # new accounts per IP address, per hour
MAX_PASSWORD = 256


@bp.before_app_request
def load_logged_in_user():
    uid = session.get("user_id")
    g.user = query("SELECT * FROM users WHERE id = ?", (uid,), one=True) if uid else None
    if g.user is not None and g.user["suspended_at"]:
        session.clear()        # a suspended account is logged out everywhere on its next request
        g.user = None


def safe_next(target):
    """Only follow redirects to a path on this site (blocks //evil.com, /\\evil.com, https://...)."""
    if not target or "\\" in target or any(ord(ch) < 32 for ch in target):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@bp.route("/register", methods=("GET", "POST"))
def register():
    role = request.values.get("role", "")
    if request.method == "POST":
        f = request.form
        email = f.get("email", "").strip().lower()
        name = f.get("name", "").strip()
        password = f.get("password", "")
        errors = []
        if over_limit(f"register:ip:{client_ip()}", *REGISTER_LIMIT):
            errors.append("Too many new accounts from your network. Please try again later.")
        if role not in ROLES:
            errors.append("Choose an account type.")
        if not name or len(name) > 120:
            errors.append("Enter your name (up to 120 characters).")
        if "@" not in email or len(email) > 254:
            errors.append("Enter a valid email.")
        if not 8 <= len(password) <= MAX_PASSWORD:
            errors.append(f"Password must be 8 to {MAX_PASSWORD} characters.")
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
            record_attempt(f"register:ip:{client_ip()}")
            lat, lng = parse_latlng(f)
            uid = execute(
                """INSERT INTO users (email, password_hash, name, role, org_name, phone, city, address, lat, lng,
                                      verification_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (email, generate_password_hash(password), name, role,
                 f.get("org_name", "").strip()[:160] or None, f.get("phone", "").strip()[:40] or None,
                 f.get("city", "").strip()[:120] or None, f.get("address", "").strip()[:200] or None, lat, lng,
                 "unverified" if role == "distributor" else "not_required"))
            session.clear()
            session["user_id"] = uid
            flash(f"Welcome to EcoServing, {name}!", "success")
            if role == "distributor":
                flash("Next step: upload your certification so we can verify your organization.", "info")
                return redirect(url_for("main.profile"))
            return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html", role=role)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:254]
        password = request.form.get("password", "")[:MAX_PASSWORD]
        email_key, ip_key = f"login:email:{email}", f"login:ip:{client_ip()}"
        if over_limit(email_key, *LOGIN_LIMIT) or over_limit(ip_key, *LOGIN_IP_LIMIT):
            flash("Too many failed attempts. Please wait 15 minutes and try again.", "error")
            return render_template("auth/login.html"), 429
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        password_ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
        if user is None or not password_ok:
            record_attempt(email_key)
            record_attempt(ip_key)
            flash("Incorrect email or password.", "error")
        elif user["suspended_at"]:
            flash("This account has been suspended. If you think this is a mistake, contact the EcoServing team.",
                  "error")
        else:
            session.clear()          # new session on login (no session fixation)
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(safe_next(request.args.get("next")) or url_for("main.dashboard"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))
