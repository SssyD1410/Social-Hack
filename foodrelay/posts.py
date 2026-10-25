"""Food offers, food requests and volunteer requests."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import execute, get_db, now_str, query
from .helpers import FOOD_TYPES, login_required, parse_latlng, role_required, verified_required
from .photos import delete_photo, save_photo
from .visibility import (can_claim_offer, can_view_offer, offer_is_expired,
                         offer_visibility_clause)

bp = Blueprint("posts", __name__)


def _required(form, fields):
    """Return a list of error messages for missing form fields."""
    return [f"{label} is required." for key, label in fields if not form.get(key, "").strip()]


def _clean(form, key):
    return form.get(key, "").strip() or None


def _photo_upload(errors, current=None):
    """Handle the optional photo field. Call after validation; returns the photo to store."""
    if errors:
        return current
    stored, error = save_photo(request.files.get("photo"))
    if error:
        errors.append(error)
        return current
    if stored or request.form.get("remove_photo"):
        delete_photo(current)
        return stored
    return current


# ---------------------------------------------------------------------------
# Food offers (posted by suppliers)
# ---------------------------------------------------------------------------

def _get_offer(offer_id):
    offer = query(
        """SELECT o.*, s.name AS supplier_name, s.org_name AS supplier_org, s.phone AS supplier_phone,
                  c.name AS claimer_name, c.org_name AS claimer_org, c.role AS claimer_role
           FROM food_offers o JOIN users s ON s.id = o.supplier_id
           LEFT JOIN users c ON c.id = o.claimed_by WHERE o.id = ?""", (offer_id,), one=True)
    if offer is None:
        abort(404)
    return offer


def _offer_form_values(form):
    size = form.get("size", "medium")
    if size not in ("small", "medium", "large"):
        size = "medium"
    visible_consumers = 1 if form.get("visible_consumers") and size == "small" else 0
    lat, lng = parse_latlng(form)
    return {
        "title": form.get("title", "").strip(),
        "description": form.get("description", "").strip(),
        "food_type": form.get("food_type", ""),
        "dietary_tags": _clean(form, "dietary_tags"),
        "quantity": form.get("quantity", "").strip(),
        "size": size,
        "location": form.get("location", "").strip(),
        "city": _clean(form, "city"),
        "lat": lat,
        "lng": lng,
        "pickup_start": _clean(form, "pickup_start"),
        "pickup_deadline": form.get("pickup_deadline", "").strip(),
        "visible_distributors": 1 if form.get("visible_distributors") else 0,
        "visible_volunteers": 0,
        "visible_consumers": visible_consumers,
    }


def _validate_offer(form, values):
    errors = _required(form, [("title", "Title"), ("description", "Description"), ("quantity", "Quantity"),
                              ("location", "Pickup location"), ("pickup_deadline", "Pickup deadline")])
    if values["food_type"] not in FOOD_TYPES:
        errors.append("Choose a food type.")
    if values["pickup_deadline"] and values["pickup_deadline"] <= now_str():
        errors.append("The pickup deadline must be in the future.")
    if values["pickup_start"] and values["pickup_deadline"] and values["pickup_start"] >= values["pickup_deadline"]:
        errors.append("Pickup start must be before the deadline.")
    if not (values["visible_distributors"] or values["visible_consumers"]):
        errors.append("Make the offer visible to at least one group.")
    if form.get("visible_consumers") and values["size"] != "small":
        errors.append("Only small offers can be shown to individual consumers.")
    return errors


OFFER_ROLES = ("supplier", "distributor", "consumer", "admin")


@bp.route("/offers")
@role_required(*OFFER_ROLES)
def offers():
    u = g.user
    clause, args = offer_visibility_clause(u)
    where, params = [clause], list(args)
    show = request.args.get("show", "available")
    if u["role"] != "supplier" and show != "all":
        where.append("o.status = 'available' AND o.pickup_deadline >= ?")
        params.append(now_str())
    if q := request.args.get("q", "").strip():
        where.append("(o.title LIKE ? OR o.description LIKE ? OR o.dietary_tags LIKE ?)")
        params += [f"%{q}%"] * 3
    if ft := request.args.get("food_type"):
        where.append("o.food_type = ?")
        params.append(ft)
    if city := request.args.get("city", "").strip():
        where.append("o.city LIKE ?")
        params.append(f"%{city}%")
    rows = query(
        f"""SELECT o.*, s.name AS supplier_name, s.org_name AS supplier_org FROM food_offers o
            JOIN users s ON s.id = o.supplier_id WHERE {' AND '.join(where)}
            ORDER BY o.status = 'available' DESC, o.pickup_deadline ASC LIMIT 200""", params)
    return render_template("offers/list.html", offers=rows, now=now_str())


@bp.route("/offers/new", methods=("GET", "POST"))
@role_required("supplier")
def new_offer():
    values = {"visible_distributors": 1, "size": "medium"}
    if request.method == "POST":
        values = _offer_form_values(request.form)
        errors = _validate_offer(request.form, values)
        values["photo"] = _photo_upload(errors)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            cols = ", ".join(values)
            oid = execute(f"INSERT INTO food_offers (supplier_id, {cols}) VALUES (?, {', '.join('?' * len(values))})",
                          (g.user["id"], *values.values()))
            flash("Your food offer is live.", "success")
            return redirect(url_for("posts.offer", offer_id=oid))
    else:
        values.update(location=g.user["address"] or "", city=g.user["city"] or "",
                      lat=g.user["lat"], lng=g.user["lng"])
    return render_template("offers/form.html", values=values, editing=False)


@bp.route("/offers/<int:offer_id>/edit", methods=("GET", "POST"))
@role_required("supplier")
def edit_offer(offer_id):
    offer = _get_offer(offer_id)
    if offer["supplier_id"] != g.user["id"]:
        abort(403)
    if offer["status"] != "available":
        flash("Only offers that haven't been claimed can be edited.", "error")
        return redirect(url_for("posts.offer", offer_id=offer_id))
    values = dict(offer)
    if request.method == "POST":
        values = _offer_form_values(request.form)
        errors = _validate_offer(request.form, values)
        values["photo"] = _photo_upload(errors, offer["photo"])
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            sets =", ".join(f"{k} = ?" for k in values)
            execute(f"UPDATE food_offers SET {sets} WHERE id = ?", (*values.values(), offer_id))
            flash("Offer updated.", "success")
            return redirect(url_for("posts.offer", offer_id=offer_id))
    return render_template("offers/form.html", values=values, editing=True, offer=offer)


@bp.route("/offers/<int:offer_id>")
@role_required(*OFFER_ROLES)
def offer(offer_id):
    o = _get_offer(offer_id)
    if not can_view_offer(g.user, o):
        abort(404)
    return render_template("offers/detail.html", offer=o, expired=offer_is_expired(o),
                           can_claim=can_claim_offer(g.user, o))


@bp.route("/offers/<int:offer_id>/claim", methods=("POST",))
@login_required
def claim_offer(offer_id):
    o = _get_offer(offer_id)
    if not can_claim_offer(g.user, o):
        flash("This offer can't be claimed (it may already be taken or expired).", "error")
        return redirect(url_for("posts.offer", offer_id=offer_id))
    # Guard against two people claiming at the same moment.
    db = get_db()
    cur = db.execute("UPDATE food_offers SET status = 'claimed', claimed_by = ?, claimed_at = ? "
                     "WHERE id = ? AND status = 'available'", (g.user["id"], now_str(), offer_id))
    db.commit()
    if cur.rowcount:
        flash("Claimed! Message the supplier to confirm pickup details.", "success")
    else:
        flash("Someone else just claimed this offer.", "error")
    return redirect(url_for("posts.offer", offer_id=offer_id))


@bp.route("/offers/<int:offer_id>/release", methods=("POST",))
@login_required
def release_offer(offer_id):
    o = _get_offer(offer_id)
    if o["status"] != "claimed" or g.user["id"] not in (o["claimed_by"], o["supplier_id"]):
        abort(403)
    execute("UPDATE food_offers SET status = 'available', claimed_by = NULL, claimed_at = NULL WHERE id = ?",
            (offer_id,))
    flash("The offer is available again.", "info")
    return redirect(url_for("posts.offer", offer_id=offer_id))


@bp.route("/offers/<int:offer_id>/complete", methods=("POST",))
@login_required
def complete_offer(offer_id):
    o = _get_offer(offer_id)
    if o["status"] != "claimed" or g.user["id"] not in (o["claimed_by"], o["supplier_id"]):
        abort(403)
    execute("UPDATE food_offers SET status = 'completed' WHERE id = ?", (offer_id,))
    flash("Marked as picked up. Thank you for rescuing food!", "success")
    return redirect(url_for("posts.offer", offer_id=offer_id))


@bp.route("/offers/<int:offer_id>/cancel", methods=("POST",))
@role_required("supplier")
def cancel_offer(offer_id):
    o = _get_offer(offer_id)
    if o["supplier_id"] != g.user["id"] or o["status"] == "completed":
        abort(403)
    execute("UPDATE food_offers SET status = 'cancelled' WHERE id = ?", (offer_id,))
    flash("Offer cancelled.", "info")
    return redirect(url_for("posts.offer", offer_id=offer_id))


# ---------------------------------------------------------------------------
# Food requests (posted by distributors, answered by suppliers)
# ---------------------------------------------------------------------------

def _get_food_request(req_id):
    r = query(
        """SELECT r.*, d.name AS distributor_name, d.org_name AS distributor_org,
                  p.name AS pledger_name, p.org_name AS pledger_org
           FROM food_requests r JOIN users d ON d.id = r.distributor_id
           LEFT JOIN users p ON p.id = r.pledged_by WHERE r.id = ?""", (req_id,), one=True)
    if r is None:
        abort(404)
    return r


@bp.route("/food-requests")
@role_required("supplier", "distributor", "volunteer", "admin")
def food_requests():
    where, params = ["1=1"], []
    mine = g.user["role"] == "distributor" and request.args.get("mine")
    if mine:
        where.append("r.distributor_id = ?")
        params.append(g.user["id"])
    else:
        where.append("r.status IN ('open', 'pledged') AND r.needed_by >= ?")
        params.append(now_str())
    if q := request.args.get("q", "").strip():
        where.append("(r.title LIKE ? OR r.description LIKE ?)")
        params += [f"%{q}%"] * 2
    if city := request.args.get("city", "").strip():
        where.append("r.city LIKE ?")
        params.append(f"%{city}%")
    rows = query(
        f"""SELECT r.*, d.name AS distributor_name, d.org_name AS distributor_org FROM food_requests r
            JOIN users d ON d.id = r.distributor_id WHERE {' AND '.join(where)}
            ORDER BY r.status = 'open' DESC, r.needed_by ASC LIMIT 200""", params)
    return render_template("food_requests/list.html", requests=rows, mine=mine)


@bp.route("/food-requests/new", methods=("GET", "POST"))
@role_required("distributor")
@verified_required
def new_food_request():
    values = {"location": g.user["address"] or "", "city": g.user["city"] or "", "lat": g.user["lat"], "lng": g.user["lng"]}
    if request.method == "POST":
        f = request.form
        values = {k: f.get(k, "").strip() for k in ("title", "description", "quantity", "location", "city", "needed_by")}
        values["lat"], values["lng"] = parse_latlng(f)
        errors = _required(f, [("title", "Title"), ("description", "Description"), ("quantity", "Quantity"),
                               ("location", "Location"), ("needed_by", "Needed by")])
        if values["needed_by"] and values["needed_by"] <= now_str():
            errors.append("'Needed by' must be in the future.")
        photo = _photo_upload(errors)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            rid = execute(
                """INSERT INTO food_requests (distributor_id, title, description, quantity, location, city, lat, lng,
                                              needed_by, photo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (g.user["id"], values["title"], values["description"], values["quantity"], values["location"],
                 values["city"] or None, values["lat"], values["lng"], values["needed_by"], photo))
            flash("Food request posted. Suppliers can now see it.", "success")
            return redirect(url_for("posts.food_request", req_id=rid))
    return render_template("food_requests/form.html", values=values)


@bp.route("/food-requests/<int:req_id>")
@role_required("supplier", "distributor", "volunteer", "admin")
def food_request(req_id):
    return render_template("food_requests/detail.html", r=_get_food_request(req_id))


@bp.route("/food-requests/<int:req_id>/<action>", methods=("POST",))
@login_required
def food_request_action(req_id, action):
    r = _get_food_request(req_id)
    u = g.user
    is_owner = r["distributor_id"] == u["id"]
    if action == "pledge" and u["role"] == "supplier" and r["status"] == "open":
        execute("UPDATE food_requests SET status = 'pledged', pledged_by = ? WHERE id = ?", (u["id"], req_id))
        flash("Thanks! The distributor has been notified via your pledge. Use chat to arrange details.", "success")
    elif action == "unpledge" and r["status"] == "pledged" and (is_owner or r["pledged_by"] == u["id"]):
        execute("UPDATE food_requests SET status = 'open', pledged_by = NULL WHERE id = ?", (req_id,))
        flash("Pledge removed; the request is open again.", "info")
    elif action == "fulfil" and is_owner and r["status"] in ("open", "pledged"):
        execute("UPDATE food_requests SET status = 'fulfilled' WHERE id = ?", (req_id,))
        flash("Marked as fulfilled.", "success")
    elif action == "close" and is_owner and r["status"] in ("open", "pledged"):
        execute("UPDATE food_requests SET status = 'closed' WHERE id = ?", (req_id,))
        flash("Request closed.", "info")
    else:
        abort(403)
    return redirect(url_for("posts.food_request", req_id=req_id))


# ---------------------------------------------------------------------------
# Volunteer requests (posted by suppliers and distributors)
# ---------------------------------------------------------------------------

def _get_vol_request(req_id):
    v = query(
        """SELECT v.*, p.name AS poster_name, p.org_name AS poster_org, p.role AS poster_role,
                  (SELECT COUNT(*) FROM volunteer_signups s WHERE s.request_id = v.id AND s.status = 'accepted') AS accepted
           FROM volunteer_requests v JOIN users p ON p.id = v.poster_id WHERE v.id = ?""", (req_id,), one=True)
    if v is None:
        abort(404)
    return v


@bp.route("/volunteer")
@login_required
def volunteer_requests():
    # Your own open requests are always listed (even if filled) so you can find them.
    where, params = ["((v.status = 'open' OR v.poster_id = ?) AND v.end_time >= ?)"], [g.user["id"], now_str()]
    if request.args.get("mine") and g.user["role"] in ("supplier", "distributor"):
        where, params = ["v.poster_id = ?"], [g.user["id"]]
    if q := request.args.get("q", "").strip():
        where.append("(v.title LIKE ? OR v.tasks LIKE ? OR v.requirements LIKE ?)")
        params += [f"%{q}%"] * 3
    if city := request.args.get("city", "").strip():
        where.append("v.city LIKE ?")
        params.append(f"%{city}%")
    rows = query(
        f"""SELECT v.*, p.name AS poster_name, p.org_name AS poster_org,
                   (SELECT COUNT(*) FROM volunteer_signups s WHERE s.request_id = v.id AND s.status = 'accepted') AS accepted
            FROM volunteer_requests v JOIN users p ON p.id = v.poster_id
            WHERE {' AND '.join(where)} ORDER BY v.poster_id = ? DESC, v.start_time ASC LIMIT 200""",
        [*params, g.user["id"]])
    return render_template("volunteer/list.html", requests=rows)


@bp.route("/volunteer/new", methods=("GET", "POST"))
@role_required("supplier", "distributor")
@verified_required
def new_volunteer_request():
    values = {"location": g.user["address"] or "", "city": g.user["city"] or "", "slots": 1,
              "lat": g.user["lat"], "lng": g.user["lng"]}
    if request.method == "POST":
        f = request.form
        values = {k: f.get(k, "").strip() for k in
                  ("title", "tasks", "requirements", "location", "city", "start_time", "end_time", "slots")}
        values["lat"], values["lng"] = parse_latlng(f)
        errors = _required(f, [("title", "Title"), ("tasks", "Tasks"), ("location", "Location"),
                               ("start_time", "Start time"), ("end_time", "End time")])
        try:
            slots = int(values["slots"] or 1)
            if not 1 <= slots <= 100:
                raise ValueError
        except ValueError:
            errors.append("Number of volunteers must be between 1 and 100.")
            slots = 1
        if values["start_time"] and values["end_time"] and values["start_time"] >= values["end_time"]:
            errors.append("End time must be after start time.")
        if values["end_time"] and values["end_time"] <= now_str():
            errors.append("The time period must be in the future.")
        photo = _photo_upload(errors)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            vid = execute(
                """INSERT INTO volunteer_requests (poster_id, title, tasks, requirements, location, city, lat, lng,
                                                   start_time, end_time, slots, photo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (g.user["id"], values["title"], values["tasks"], values["requirements"] or None,
                 values["location"], values["city"] or None, values["lat"], values["lng"],
                 values["start_time"], values["end_time"], slots, photo))
            flash("Volunteer request posted.", "success")
            return redirect(url_for("posts.volunteer_request", req_id=vid))
    return render_template("volunteer/form.html", values=values)


@bp.route("/volunteer/<int:req_id>")
@login_required
def volunteer_request(req_id):
    v = _get_vol_request(req_id)
    signups, my_signup = [], None
    if v["poster_id"] == g.user["id"] or g.user["role"] == "admin":
        signups = query(
            """SELECT s.*, u.name, u.city, u.bio FROM volunteer_signups s JOIN users u ON u.id = s.volunteer_id
               WHERE s.request_id = ? ORDER BY s.status = 'pending' DESC, s.created_at""", (req_id,))
    if g.user["role"] == "volunteer":
        my_signup = query("SELECT * FROM volunteer_signups WHERE request_id = ? AND volunteer_id = ?",
                          (req_id, g.user["id"]), one=True)
    return render_template("volunteer/detail.html", v=v, signups=signups, my_signup=my_signup, now=now_str())


@bp.route("/volunteer/<int:req_id>/apply", methods=("POST",))
@role_required("volunteer")
def apply_volunteer(req_id):
    v = _get_vol_request(req_id)
    if v["status"] != "open" or v["end_time"] < now_str():
        flash("This request is no longer accepting volunteers.", "error")
    else:
        msg = request.form.get("message", "").strip() or None
        existing = query("SELECT * FROM volunteer_signups WHERE request_id = ? AND volunteer_id = ?",
                         (req_id, g.user["id"]), one=True)
        if existing:
            execute("UPDATE volunteer_signups SET status = 'pending', message = ? WHERE id = ?", (msg, existing["id"]))
        else:
            execute("INSERT INTO volunteer_signups (request_id, volunteer_id, message) VALUES (?, ?, ?)",
                    (req_id, g.user["id"], msg))
        flash("You've signed up! The organizer will confirm.", "success")
    return redirect(url_for("posts.volunteer_request", req_id=req_id))


@bp.route("/volunteer/<int:req_id>/withdraw", methods=("POST",))
@role_required("volunteer")
def withdraw_volunteer(req_id):
    execute("UPDATE volunteer_signups SET status = 'withdrawn' WHERE request_id = ? AND volunteer_id = ?",
            (req_id, g.user["id"]))
    _refresh_vol_status(req_id)
    flash("Thanks for letting us know. Your spot has been re-listed for other volunteers.", "info")
    return redirect(url_for("posts.volunteer_request", req_id=req_id))


def _refresh_vol_status(req_id):
    """Keep a request 'filled' exactly when accepted signups reach the slot count."""
    v = _get_vol_request(req_id)
    if v["status"] == "closed":
        return
    new = "filled" if v["accepted"] >= v["slots"] else "open"
    if new != v["status"]:
        execute("UPDATE volunteer_requests SET status = ? WHERE id = ?", (new, req_id))


@bp.route("/volunteer/signups/<int:signup_id>/<decision>", methods=("POST",))
@role_required("supplier", "distributor")
def decide_signup(signup_id, decision):
    s = query("SELECT s.*, v.poster_id FROM volunteer_signups s JOIN volunteer_requests v ON v.id = s.request_id "
              "WHERE s.id = ?", (signup_id,), one=True)
    if s is None or s["poster_id"] != g.user["id"] or decision not in ("accept", "decline"):
        abort(403)
    execute("UPDATE volunteer_signups SET status = ? WHERE id = ?",
            ("accepted" if decision == "accept" else "declined", signup_id))
    _refresh_vol_status(s["request_id"])
    return redirect(url_for("posts.volunteer_request", req_id=s["request_id"]))


@bp.route("/volunteer/<int:req_id>/<action>", methods=("POST",))
@role_required("supplier", "distributor")
def volunteer_request_action(req_id, action):
    v = _get_vol_request(req_id)
    if v["poster_id"] != g.user["id"] or action not in ("close", "reopen"):
        abort(403)
    if action == "close":
        execute("UPDATE volunteer_requests SET status = 'closed' WHERE id = ?", (req_id,))
    else:
        execute("UPDATE volunteer_requests SET status = 'open' WHERE id = ?", (req_id,))
        _refresh_vol_status(req_id)
    return redirect(url_for("posts.volunteer_request", req_id=req_id))
