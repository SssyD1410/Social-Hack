"""The automated four-screen demo (run with `python run_demo.py`).

Demo mode is never switched on by the normal app or by an environment variable. `main()` below builds a
separate app with DEMO_MODE on, a throwaway database that is re-seeded on every start, no rate limits and
automatic logins for the seeded demo accounts, so it must never be deployed.

How four logins share one browser: each pane of /demo is an iframe at /demo/frame/<role>/..., and a small WSGI
wrapper makes the app think it is mounted at that prefix. Every pane therefore gets its own session cookie
(named after the role) while url_for() still produces working links. A script in static/demo.js then drives
the four panes like four people using the real site.
"""

import os
import re

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from flask.sessions import SecureCookieSessionInterface

from .auth import safe_next
from .db import execute, init_db, query

ROLE_ACCOUNTS = {
    "supplier": "bakery@ecoserving.test",
    "distributor": "shelter@ecoserving.test",
    "volunteer": "volunteer@ecoserving.test",
    "consumer": "consumer@ecoserving.test",
    "admin": "admin@ecoserving.test",
}
FRAME_PREFIX = re.compile(r"^(/demo/frame/(%s))(/.*)?$" % "|".join(ROLE_ACCOUNTS))

bp = Blueprint("demo", __name__)


class _FramePrefix:
    """Serve /demo/frame/<role>/<path> as /<path> with SCRIPT_NAME = /demo/frame/<role>."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        m = FRAME_PREFIX.match(environ.get("PATH_INFO", ""))
        if m:
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + m.group(1)
            environ["PATH_INFO"] = m.group(3) or "/"
            environ["ecoserving.demo_role"] = m.group(2)
        return self.app(environ, start_response)


class _PerRoleSessions(SecureCookieSessionInterface):
    def get_cookie_name(self, app):
        role = request.environ.get("ecoserving.demo_role")
        return f"es_demo_{role}" if role else super().get_cookie_name(app)


@bp.route("/demo")
def page():
    return render_template("demo.html")


@bp.route("/_demo_login")
def login():
    """Inside a pane: log that pane in as its role's demo account."""
    role = request.environ.get("ecoserving.demo_role")
    if role not in ROLE_ACCOUNTS:
        abort(404)
    user = query("SELECT id FROM users WHERE email = ?", (ROLE_ACCOUNTS[role],), one=True)
    session.clear()
    session["user_id"] = user["id"]
    nxt = safe_next(request.args.get("next"))
    return redirect(request.script_root + nxt if nxt else url_for("main.dashboard"))


def plant_scam_offer():
    """A fictional scam post for the finale: asks for a fee up front, which real EcoServing offers never do."""
    from werkzeug.security import generate_password_hash
    from .seed import DEMO_PASSWORD, _t
    scammer = query("SELECT id FROM users WHERE email = 'quickmeals@ecoserving.test'", one=True)
    sid = scammer["id"] if scammer else execute(
        "INSERT INTO users (email, password_hash, name, role, org_name, city) VALUES (?, ?, ?, 'supplier', ?, ?)",
        ("quickmeals@ecoserving.test", generate_password_hash(DEMO_PASSWORD), "Chris Doe", "QuickMeals Co", "Minneapolis, MN"))
    return execute(
        """INSERT INTO food_offers (supplier_id, title, description, food_type, quantity, size, location, city, lat, lng,
                                    pickup_deadline, visible_distributors, visible_consumers)
           VALUES (?, ?, ?, 'Prepared meals', '4 meal boxes', 'small', '1200 Hennepin Ave', 'Minneapolis, MN',
                   44.9724, -93.2870, ?, 1, 1)""",
        (sid, "FREE food box: pay $15 delivery fee first",
         "Free meal boxes for everyone! To reserve yours, send the $15 delivery fee by gift card and text us the code.",
         _t(6)))


@bp.route("/demo/plant-scam", methods=("POST",))
def plant_scam():
    plant_scam_offer()
    return jsonify(ok=True)


@bp.route("/demo/reset", methods=("POST",))
def reset():
    """Wipe the demo database and load fresh demo data (called before every run)."""
    from .seed import seed
    init_db()
    seed()
    return jsonify(ok=True)


def init_app(app):
    app.session_interface = _PerRoleSessions()
    app.wsgi_app = _FramePrefix(app.wsgi_app)
    app.register_blueprint(bp)


def port_in_use(port, host="127.0.0.1"):
    """True when something is already listening there. (On Windows two programs can share a port, which would
    split the demo's requests between two servers with different data, so the demo refuses to start instead.)"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def build_url(port=5001, beat=None, pace=None, speed=None, admin=None, autostart=False):
    """The demo address with the chosen timing options (only the ones given are added)."""
    options = {"beat": beat, "pace": pace, "speed": speed, "admin": admin, "autostart": 1 if autostart else None}
    query_string = "&".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                            for k, v in options.items() if v is not None)
    return f"http://127.0.0.1:{port}/demo" + (f"?{query_string}" if query_string else "")


def main(argv=None):
    import argparse
    import threading
    import webbrowser

    ap = argparse.ArgumentParser(description="Run the EcoServing four-screen demo.")
    ap.add_argument("--beat", type=float, metavar="SECONDS", help="pause after each caption (default 4)")
    ap.add_argument("--pace", type=float, metavar="X", help="cursor and typing slowness (default 1.5; 1 = quicker)")
    ap.add_argument("--speed", type=float, metavar="X", help="overall speed (default 1; 2 = twice as fast)")
    ap.add_argument("--admin", type=float, metavar="X", help="extra speed of the admin window (default 2.2)")
    ap.add_argument("--autostart", action="store_true", help="start playing as soon as the page opens")
    ap.add_argument("--open", action="store_true", help="open the demo in your browser")
    ap.add_argument("--port", type=int, default=5001)
    args = ap.parse_args(argv)
    port = args.port
    if port_in_use(port):
        raise SystemExit(f"Port {port} is already in use, probably by another copy of the demo. Stop that one "
                         f"(Ctrl+C in its window) or pick another port with --port {port + 1}.")

    from . import create_app
    from .seed import seed

    instance = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance")
    os.makedirs(instance, exist_ok=True)
    db_path = os.path.join(instance, "demo.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)
    app = create_app({"DEMO_MODE": True, "DATABASE": db_path, "RATELIMIT_ENABLED": False,
                      "SECRET_KEY": "demo-only-not-secret"})
    with app.app_context():
        seed()
    url = build_url(port, args.beat, args.pace, args.speed, args.admin, args.autostart)
    print(f"EcoServing demo: open {url}  (Ctrl+C to stop)")
    if args.open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
