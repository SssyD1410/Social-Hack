import os
import secrets

from flask import Flask, abort, g, request, session

from . import db


def _instance_secret(instance_path):
    """A random secret key, made on first run and kept in instance/secret_key (never committed)."""
    path = os.path.join(instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("ECOSERVING_SECRET_KEY"),
        DATABASE=os.path.join(app.instance_path, "ecoserving.sqlite"),
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,           # no single text field needs more than this
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",            # cookies aren't sent on cross-site POSTs
        SESSION_COOKIE_SECURE=os.environ.get("ECOSERVING_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = _instance_secret(app.instance_path)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    # --- CSRF protection for every state-changing request -------------------
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("TESTING_SKIP_CSRF"):
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
            if not secrets.compare_digest(sent, session.get("_csrf", "")) or not sent:
                abort(400, "Invalid or missing CSRF token. Reload the page and try again.")

    app.jinja_env.globals["csrf_token"] = csrf_token

    # --- Security headers -----------------------------------------------------
    # Every inline <script> carries this per-request nonce, so the Content Security Policy can refuse any
    # script that an attacker manages to inject into a page.
    def csp_nonce():
        if "csp_nonce" not in g:
            g.csp_nonce = secrets.token_urlsafe(16)
        return g.csp_nonce

    app.jinja_env.globals["csp_nonce"] = csp_nonce

    @app.after_request
    def security_headers(resp):
        csp = "; ".join([
            "default-src 'self'",
            f"script-src 'self' 'nonce-{csp_nonce()}' https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
            "img-src 'self' data: blob: https://server.arcgisonline.com",
            "connect-src 'self' https://router.project-osrm.org https://nominatim.openstreetmap.org",
            "font-src 'self'",
            "media-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ])
        resp.headers.setdefault("Content-Security-Policy", csp)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=(), payment=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    from . import admin, auth, chat, main, posts, reports
    for bp in (auth.bp, main.bp, posts.bp, chat.bp, admin.bp, reports.bp):
        app.register_blueprint(bp)

    from .helpers import register_template_helpers
    register_template_helpers(app)
    from . import photos
    photos.register(app)

    return app
