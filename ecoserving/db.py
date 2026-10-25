import os
import sqlite3
from datetime import datetime

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def now_str():
    """Current local time in the same format as <input type="datetime-local">."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _run_script(name):
    with current_app.open_resource(name) as f:
        get_db().executescript(f.read().decode("utf8"))


def init_db():
    _run_script("schema.sql")
    _run_script("schema_additions.sql")


# Both commands wipe every account and post, so they ask first (skip with --yes).
@click.command("init-db")
@click.confirmation_option(prompt="This deletes ALL data in the database. Continue?")
@with_appcontext
def init_db_command():
    """Drop and recreate all tables."""
    init_db()
    click.echo("Initialized the database.")


@click.command("seed")
@click.confirmation_option(prompt="This deletes ALL data and adds demo accounts with a public password. "
                                  "Never do this on a live site. Continue?")
@with_appcontext
def seed_command():
    """Reset the database and fill it with demo data."""
    from .seed import seed
    init_db()
    seed()
    click.echo("Seeded demo data. See README for demo logins.")


@click.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--name", prompt=True, default="EcoServing Admin")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_admin_command(email, name, password):
    """Create an administrator account (admins verify distributors)."""
    from werkzeug.security import generate_password_hash
    if not 8 <= len(password) <= 256:
        raise click.BadParameter("use 8 to 256 characters", param_hint="password")
    if query("SELECT 1 FROM users WHERE email = ?", (email,), one=True):
        raise click.ClickException(f"An account for {email} already exists.")
    execute("INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, 'admin')",
            (email.strip(), generate_password_hash(password), name.strip()))
    click.echo(f"Created admin {email}.")


def migrate():
    """Add columns and tables introduced after a database was created."""
    db = get_db()
    added = {"users": [("lat", "REAL"), ("lng", "REAL"), ("suspended_at", "TEXT"), ("suspended_reason", "TEXT")]}
    for table in ("food_offers", "food_requests", "volunteer_requests"):
        added[table] = [("lat", "REAL"), ("lng", "REAL"), ("photo", "TEXT")]
    for table, columns in added.items():
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for col, kind in columns:
            if col not in cols:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    db.commit()
    _run_script("schema_additions.sql")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(create_admin_command)
    with app.app_context():
        if not os.path.exists(app.config["DATABASE"]):
            init_db()
        else:
            migrate()
