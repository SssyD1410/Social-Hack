import os
import uuid

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)

from .db import execute, now_str, query
from .helpers import ROLES, distance_km, login_required, parse_latlng
from .visibility import offer_visibility_clause

bp = Blueprint("main", __name__)

ALLOWED_DOC_EXT = {".pdf", ".png", ".jpg", ".jpeg"}
DOC_TYPES = ["Charity / non-profit registration", "Food safety certificate",
             "Food handler training", "Insurance certificate", "Other proof of eligibility"]


@bp.route("/")
def index():
    stats = query(
        """SELECT (SELECT COUNT(*) FROM food_offers WHERE status IN ('claimed','completed')) AS rescued,
                  (SELECT COUNT(*) FROM users WHERE role = 'supplier') AS suppliers,
                  (SELECT COUNT(*) FROM users WHERE role = 'distributor' AND verification_status = 'verified') AS distributors,
                  (SELECT COUNT(*) FROM users WHERE role = 'volunteer') AS volunteers""", one=True)
    return render_template("index.html", stats=stats)


@bp.route("/favicon.ico")
def favicon():
    # Browsers ask for /favicon.ico directly; serve the generated one instead of a 404.
    return send_from_directory(os.path.join(current_app.static_folder, "favicon"), "favicon.ico")


@bp.route("/learn")
@bp.route("/learn/<role>")
def learn(role="supplier"):
    if role not in ROLES:
        abort(404)
    return render_template("learn/index.html", role=role)


MAP_LIMIT = 6


def _point(row, title, url, subtitle=""):
    return {"lat": row["lat"], "lng": row["lng"], "title": title, "url": url, "subtitle": subtitle}


def _dashboard_map(u, now):
    """Your own posts, plus the most relevant counterparts (nearest first, else soonest)."""
    if u["role"] == "supplier":
        posts = [_point(o, o["title"], url_for("posts.offer", offer_id=o["id"]), "Your offer") for o in query(
            "SELECT * FROM food_offers WHERE supplier_id = ? AND status IN ('available', 'claimed') "
            "AND lat IS NOT NULL", (u["id"],))]
        rows = query("""SELECT r.*, d.org_name, d.name FROM food_requests r JOIN users d ON d.id = r.distributor_id
                        WHERE r.status = 'open' AND r.needed_by >= ? AND r.lat IS NOT NULL ORDER BY r.needed_by""", (now,))
        targets = [_point(r, r["title"], url_for("posts.food_request", req_id=r["id"]), r["org_name"] or r["name"]) for r in rows]
        label = "food requests from distributors"
    elif u["role"] == "distributor":
        posts = [_point(r, r["title"], url_for("posts.food_request", req_id=r["id"]), "Your food request") for r in query(
            "SELECT * FROM food_requests WHERE distributor_id = ? AND status IN ('open', 'pledged') AND lat IS NOT NULL",
            (u["id"],))]
        clause, args = offer_visibility_clause(u)
        rows = query(f"""SELECT o.*, s.org_name, s.name FROM food_offers o JOIN users s ON s.id = o.supplier_id
                         WHERE {clause} AND o.status = 'available' AND o.pickup_deadline >= ? AND o.lat IS NOT NULL
                         ORDER BY o.pickup_deadline""", (*args, now))
        targets = [_point(o, o["title"], url_for("posts.offer", offer_id=o["id"]), o["org_name"] or o["name"]) for o in rows]
        label = "food offers from suppliers"
    elif u["role"] == "volunteer":
        posts = []
        rows = query("""SELECT v.*, p.org_name, p.name FROM volunteer_requests v JOIN users p ON p.id = v.poster_id
                        WHERE v.status = 'open' AND v.end_time >= ? AND v.lat IS NOT NULL ORDER BY v.start_time""", (now,))
        targets = [_point(v, v["title"], url_for("posts.volunteer_request", req_id=v["id"]), v["org_name"] or v["name"])
                   for v in rows]
        label = "volunteer requests"
    else:
        posts = []
        clause, args = offer_visibility_clause(u)
        rows = query(f"""SELECT o.*, s.org_name, s.name FROM food_offers o JOIN users s ON s.id = o.supplier_id
                         WHERE {clause} AND o.status = 'available' AND o.pickup_deadline >= ? AND o.lat IS NOT NULL
                         ORDER BY o.pickup_deadline""", (*args, now))
        targets = [_point(o, o["title"], url_for("posts.offer", offer_id=o["id"]), o["org_name"] or o["name"]) for o in rows]
        label = "food offers"

    me = None
    if u["lat"] is not None:
        me = {"lat": u["lat"], "lng": u["lng"], "title": "You", "subtitle": u["address"] or u["city"] or ""}
    elif posts:
        me = {**posts[0], "title": "You (from your first post)"}
    if me:
        # Python's sort is stable, so ties keep the soonest-deadline order from SQL.
        targets.sort(key=lambda t: distance_km(me["lat"], me["lng"], t["lat"], t["lng"]))
        for t in targets:
            t["km"] = round(distance_km(me["lat"], me["lng"], t["lat"], t["lng"]), 1)
    return {"me": me, "posts": posts, "targets": targets[:MAP_LIMIT], "total": len(targets),
            "label": label, "limit": MAP_LIMIT}


@bp.route("/dashboard")
@login_required
def dashboard():
    u = g.user
    now = now_str()
    if u["role"] == "admin":
        return redirect(url_for("admin.index"))
    ctx = {"now": now, "map_data": _dashboard_map(u, now)}

    if u["role"] == "supplier":
        ctx["my_offers"] = query(
            """SELECT o.*, c.name AS claimer_name, c.org_name AS claimer_org FROM food_offers o
               LEFT JOIN users c ON c.id = o.claimed_by
               WHERE o.supplier_id = ? ORDER BY o.status = 'available' DESC, o.created_at DESC LIMIT 20""",
            (u["id"],))
        ctx["food_requests"] = query(
            """SELECT r.*, d.org_name, d.name FROM food_requests r JOIN users d ON d.id = r.distributor_id
               WHERE r.status = 'open' AND r.needed_by >= ? ORDER BY r.needed_by LIMIT 6""", (now,))
    elif u["role"] != "volunteer":
        clause, args = offer_visibility_clause(u)
        ctx["available_offers"] = query(
            f"""SELECT o.*, s.org_name, s.name FROM food_offers o JOIN users s ON s.id = o.supplier_id
                WHERE {clause} AND o.status = 'available' AND o.pickup_deadline >= ?
                ORDER BY o.pickup_deadline LIMIT 6""", (*args, now))
        ctx["my_claims"] = query(
            """SELECT o.*, s.org_name, s.name FROM food_offers o JOIN users s ON s.id = o.supplier_id
               WHERE o.claimed_by = ? ORDER BY o.status = 'claimed' DESC, o.pickup_deadline DESC LIMIT 20""",
            (u["id"],))

    if u["role"] == "distributor":
        ctx["my_food_requests"] = query(
            """SELECT r.*, p.org_name AS pledger_org, p.name AS pledger_name FROM food_requests r
               LEFT JOIN users p ON p.id = r.pledged_by
               WHERE r.distributor_id = ? ORDER BY r.created_at DESC LIMIT 20""", (u["id"],))

    if u["role"] in ("supplier", "distributor"):
        ctx["my_vol_requests"] = query(
            """SELECT v.*,
                      (SELECT COUNT(*) FROM volunteer_signups s WHERE s.request_id = v.id AND s.status = 'pending') AS pending,
                      (SELECT COUNT(*) FROM volunteer_signups s WHERE s.request_id = v.id AND s.status = 'accepted') AS accepted
               FROM volunteer_requests v WHERE v.poster_id = ? ORDER BY v.start_time DESC LIMIT 20""", (u["id"],))

    if u["role"] == "volunteer":
        ctx["my_signups"] = query(
            """SELECT s.*, v.title, v.start_time, v.end_time, v.location, v.id AS vid, p.org_name, p.name
               FROM volunteer_signups s JOIN volunteer_requests v ON v.id = s.request_id
               JOIN users p ON p.id = v.poster_id
               WHERE s.volunteer_id = ? ORDER BY v.start_time DESC""", (u["id"],))
        ctx["open_vol_requests"] = query(
            """SELECT v.*, p.org_name, p.name FROM volunteer_requests v JOIN users p ON p.id = v.poster_id
               WHERE v.status = 'open' AND v.end_time >= ?
                 AND v.id NOT IN (SELECT request_id FROM volunteer_signups WHERE volunteer_id = ?)
               ORDER BY v.start_time LIMIT 6""", (now, u["id"]))

    return render_template(f"dashboard/{u['role']}.html", **ctx)


@bp.route("/profile", methods=("GET", "POST"))
@login_required
def profile():
    u = g.user
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        lat, lng = parse_latlng(f)
        if not name:
            flash("Name is required.", "error")
        else:
            execute(
                """UPDATE users SET name = ?, org_name = ?, phone = ?, city = ?, address = ?, bio = ?, lat = ?, lng = ?,
                                    registration_number = COALESCE(?, registration_number)
                   WHERE id = ?""",
                (name, f.get("org_name", "").strip() or None, f.get("phone", "").strip() or None,
                 f.get("city", "").strip() or None, f.get("address", "").strip() or None,
                 f.get("bio", "").strip() or None, lat, lng, f.get("registration_number", "").strip() or None,
                 u["id"]))
            flash("Profile saved.", "success")
        return redirect(url_for("main.profile"))

    docs = query("SELECT * FROM verification_documents WHERE user_id = ? ORDER BY uploaded_at DESC", (u["id"],))
    return render_template("profile.html", docs=docs, doc_types=DOC_TYPES)


@bp.route("/profile/documents", methods=("POST",))
@login_required
def upload_document():
    u = g.user
    if u["role"] != "distributor":
        abort(403)
    file = request.files.get("document")
    doc_type = request.form.get("doc_type", "")
    if doc_type not in DOC_TYPES:
        flash("Choose a document type.", "error")
        return redirect(url_for("main.profile"))
    if not file or not file.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("main.profile"))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_DOC_EXT:
        flash("Upload a PDF, PNG or JPG file.", "error")
        return redirect(url_for("main.profile"))
    stored = f"{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
    execute("INSERT INTO verification_documents (user_id, doc_type, stored_name, original_name) VALUES (?, ?, ?, ?)",
            (u["id"], doc_type, stored, os.path.basename(file.filename)[:200]))
    flash("Document uploaded.", "success")
    return redirect(url_for("main.profile"))


@bp.route("/profile/submit-verification", methods=("POST",))
@login_required
def submit_verification():
    u = g.user
    if u["role"] != "distributor" or u["verification_status"] in ("pending", "verified"):
        abort(400)
    if not u["registration_number"]:
        flash("Add your organization's registration number first.", "error")
        return redirect(url_for("main.profile"))
    if not query("SELECT 1 FROM verification_documents WHERE user_id = ?", (u["id"],), one=True):
        flash("Upload at least one certification document first.", "error")
        return redirect(url_for("main.profile"))
    execute("UPDATE users SET verification_status = 'pending', verification_note = NULL WHERE id = ?", (u["id"],))
    flash("Submitted! An administrator will review your documents.", "success")
    return redirect(url_for("main.profile"))


@bp.route("/documents/<int:doc_id>")
@login_required
def document(doc_id):
    doc = query("SELECT * FROM verification_documents WHERE id = ?", (doc_id,), one=True)
    if doc is None:
        abort(404)
    if doc["user_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], doc["stored_name"],
                               download_name=doc["original_name"])


@bp.route("/users/<int:user_id>")
@login_required
def user_profile(user_id):
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if user is None or user["role"] == "admin":
        abort(404)
    return render_template("user.html", person=user)
