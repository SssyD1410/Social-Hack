import os
import secrets

from flask import Flask, abort, request, session

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
        SECRET_KEY=os.environ.get("FOODRELAY_SECRET_KEY"),
        DATABASE=os.path.join(app.instance_path, "foodrelay.sqlite"),
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
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
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not sent or sent != session.get("_csrf"):
                abort(400, "Invalid or missing CSRF token. Reload the page and try again.")

    app.jinja_env.globals["csrf_token"] = csrf_token

    from . import admin, auth, chat, main, posts
    for bp in (auth.bp, main.bp, posts.bp, chat.bp, admin.bp):
        app.register_blueprint(bp)

    from .helpers import register_template_helpers
    register_template_helpers(app)
    from . import photos
    photos.register(app)

    return app
