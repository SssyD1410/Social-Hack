"""Photos on offers and requests: uploads by users, with a real stock photo as the fallback.

Stock photos live in static/photos (1600px wide) and static/photos/sm (720px), with their
licences and sources in static/photos/credits.json (shown on /credits).
"""

import json
import os
import re
import uuid

from flask import current_app, url_for

# Stock photos per food type; a post picks one by its id so neighbours rarely look the same.
STOCK_BY_TYPE = {
    "Prepared meals": ["dinner-served", "lunch-plate", "chefs-kitchen"],
    "Bakery & bread": ["fresh-bread", "bakery-shelves", "bakery-counter"],
    "Fruit & vegetables": ["vegetables", "vegetable-basket", "apple-crates", "market-produce"],
    "Dairy & eggs": ["eggs", "eggs-bowl", "cheese"],
    "Meat & fish": ["fish", "fish-market"],
    "Packaged & dry goods": ["canned-greens", "pantry-jars", "canned-applesauce"],
    "Drinks": ["coffee", "cappuccino"],
    "Mixed": ["market-produce", "fruit", "apple-crates"],
}
# Food requests have no food type, so guess one from their words.
KEYWORDS = [
    ("Bakery & bread", r"bread|bak|loa|pastr|bagel|roll|muffin|croissant"),
    ("Fruit & vegetables", r"fruit|veg|produce|apple|banana|salad|green"),
    ("Dairy & eggs", r"dairy|milk|egg|cheese|yogh?urt"),
    ("Meat & fish", r"meat|fish|chicken|beef|pork|protein"),
    ("Drinks", r"drink|coffee|juice|water|tea\b"),
    ("Prepared meals", r"meal|dinner|lunch|breakfast|soup|hot food|cooked|portion"),
    ("Packaged & dry goods", r"canned|cans|pasta|rice|dry|shelf|staple|pantry|cereal"),
]
REQUEST_DEFAULT = ["pantry-aisle", "canned-greens"]
VOLUNTEER_STOCK = [(r"kitchen|cook|serv|meal|prep", ["chefs-kitchen"]),
                   (r"", ["food-bank-sorting", "pantry-aisle"])]

ALLOWED = {"jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "png": b"\x89PNG", "webp": b"RIFF"}
PHOTO_DIR = "photos"   # inside UPLOAD_FOLDER


def _pick(names, row_id):
    return names[(row_id or 0) % len(names)]


def stock_name(kind, row):
    """Name of the stock photo for a post that has no photo of its own."""
    if kind == "offer":
        return _pick(STOCK_BY_TYPE.get(row["food_type"], STOCK_BY_TYPE["Mixed"]), row["id"])
    text = " ".join(str(row[k] or "") for k in row.keys() if k in ("title", "description", "tasks")).lower()
    if kind == "volunteer":
        return next(_pick(names, row["id"]) for pattern, names in VOLUNTEER_STOCK if re.search(pattern, text))
    for food_type, pattern in KEYWORDS:
        if re.search(pattern, text):
            return _pick(STOCK_BY_TYPE[food_type], row["id"])
    return _pick(REQUEST_DEFAULT, row["id"])


def photo_url(kind, row, size="sm"):
    """URL of the photo shown for an offer, food request or volunteer request."""
    own = row["photo"] if "photo" in row.keys() else None
    if own:
        return url_for("main.photo", name=own)
    name = stock_name(kind, row)
    return url_for("static", filename=f"photos/{'sm/' if size == 'sm' else ''}{name}.jpg")


def photo_alt(kind, row):
    if "photo" in row.keys() and row["photo"]:
        return f"Photo of {row['title']}"
    return stock_credits()[stock_name(kind, row)]["alt"]


def stock_credits():
    """Stock photo metadata by name (cached on the app)."""
    cache = current_app.extensions.get("stock_credits")
    if cache is None:
        with open(os.path.join(current_app.static_folder, "photos", "credits.json"), encoding="utf-8") as f:
            cache = {c["name"]: c for c in json.load(f)}
        current_app.extensions["stock_credits"] = cache
    return cache


def photo_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], PHOTO_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def save_photo(file):
    """Save an uploaded photo. Returns (stored name, None), (None, error) or (None, None) when no file."""
    if not file or not file.filename:
        return None, None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    head = file.stream.read(12)
    file.stream.seek(0)
    if ext not in ALLOWED or not head.startswith(ALLOWED[ext]) or (ext == "webp" and head[8:12] != b"WEBP"):
        return None, "Photos must be JPG, PNG or WebP images."
    stored = f"{uuid.uuid4().hex}.{'jpg' if ext == 'jpeg' else ext}"
    file.save(os.path.join(photo_folder(), stored))
    return stored, None


def delete_photo(name):
    if name:
        try:
            os.remove(os.path.join(photo_folder(), os.path.basename(name)))
        except OSError:
            pass


def register(app):
    app.add_template_global(photo_url)
    app.add_template_global(photo_alt)
    app.add_template_global(lambda name: stock_credits()[name]["alt"], "stock_alt")
