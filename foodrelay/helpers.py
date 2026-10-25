import functools
import math
from datetime import datetime

from flask import flash, g, redirect, request, url_for
from markupsafe import Markup, escape

from .db import query

ROLES = {
    "supplier": {
        "label": "Supplier",
        "tagline": "Shops, bakeries and restaurants with surplus food to give away.",
        "icon": "store",
    },
    "distributor": {
        "label": "Distributor",
        "tagline": "Verified organizations that deliver food to people in need.",
        "icon": "truck",
    },
    "volunteer": {
        "label": "Volunteer",
        "tagline": "Individuals who give their time to pick up and hand out food.",
        "icon": "hand-heart",
    },
    "consumer": {
        "label": "Consumer",
        "tagline": "Anyone who could use a free meal or groceries nearby.",
        "icon": "utensils",
    },
}

FOOD_TYPES = [
    "Prepared meals", "Bakery & bread", "Fruit & vegetables", "Dairy & eggs",
    "Meat & fish", "Packaged & dry goods", "Drinks", "Mixed",
]


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Please log in first.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped(**kwargs):
            if g.user["role"] not in roles:
                flash("That page isn't available for your account type.", "error")
                return redirect(url_for("main.dashboard"))
            return view(**kwargs)
        return wrapped
    return decorator


def is_verified(user):
    """Distributors must be verified; every other role is trusted by default."""
    return user["role"] != "distributor" or user["verification_status"] == "verified"


def verified_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if not is_verified(g.user):
            flash("Your organization needs to be verified before you can do that. "
                  "Upload your certification on your profile.", "error")
            return redirect(url_for("main.profile"))
        return view(**kwargs)
    return wrapped


def parse_latlng(form):
    """Read lat/lng from a form's hidden map-picker fields; (None, None) if missing or invalid."""
    try:
        lat, lng = float(form.get("lat", "")), float(form.get("lng", ""))
    except ValueError:
        return None, None
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return round(lat, 6), round(lng, 6)
    return None, None


def distance_km(a_lat, a_lng, b_lat, b_lng):
    """Great-circle distance; None when either point is unknown."""
    if None in (a_lat, a_lng, b_lat, b_lng):
        return None
    a_lat, a_lng, b_lat, b_lng = map(math.radians, (a_lat, a_lng, b_lat, b_lng))
    h = math.sin((b_lat - a_lat) / 2) ** 2 + math.cos(a_lat) * math.cos(b_lat) * math.sin((b_lng - a_lng) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def unread_count(user_id):
    row = query(
        """SELECT COUNT(*) AS n FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE (c.user_low = ? OR c.user_high = ?) AND m.sender_id != ? AND m.read_at IS NULL""",
        (user_id, user_id, user_id), one=True)
    return row["n"]


def fmt_dt(value):
    if not value:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%a %d %b, %H:%M")
        except ValueError:
            continue
    return value


def icon(name, label=None, cls=""):
    """Inline SVG icon from static/icons.svg (Lucide). Decorative unless a label is given."""
    href = f"{url_for('static', filename='icons.svg')}#{escape(name)}"
    a11y = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    return Markup(f'<svg class="icon {escape(cls)}" {a11y}><use href="{href}"></use></svg>')


def register_template_helpers(app):
    app.jinja_env.filters["dt"] = fmt_dt
    app.jinja_env.globals["icon"] = icon

    @app.context_processor
    def inject():
        return {
            "ROLES": ROLES,
            "FOOD_TYPES": FOOD_TYPES,
            "unread": unread_count(g.user["id"]) if getattr(g, "user", None) else 0,
            "is_verified": is_verified,
        }
