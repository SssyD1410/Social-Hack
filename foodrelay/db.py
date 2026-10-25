import os
import sqlite3
from datetime import datetime

import click
from flask import current_app, g


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


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


@click.command("init-db")
def init_db_command():
    """Drop and recreate all tables."""
    init_db()
    click.echo("Initialized the database.")


@click.command("seed")
def seed_command():
    """Reset the database and fill it with demo data."""
    from .seed import seed
    init_db()
    seed()
    click.echo("Seeded demo data. See README for demo logins.")


def migrate():
    """Add columns introduced after a database was created."""
    db = get_db()
    for table in ("users", "food_offers", "food_requests", "volunteer_requests"):
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for col, kind in (("lat", "REAL"), ("lng", "REAL"), ("photo", "TEXT")):
            if col not in cols and not (table == "users" and col == "photo"):
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)
    with app.app_context():
        if not os.path.exists(app.config["DATABASE"]):
            init_db()
        else:
            migrate()
