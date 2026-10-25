"""Scam and fraud reports: any user can report a post or another user; admins review them."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .chat import _can_view_ref, _ref_info
from .db import execute, now_str, query
from .helpers import login_required, over_limit, record_attempt, role_required

bp = Blueprint("reports", __name__)

CATEGORIES = {
    "scam": "Scam (asking for money, fees or personal details)",
    "fraud": "Fake organization or impersonation",
    "unsafe_food": "Unsafe, spoiled or misrepresented food",
    "harassment": "Harassment or threatening behaviour",
    "spam": "Spam or fake posts",
    "other": "Something else",
}
TARGET_TYPES = ("offer", "food_request", "volunteer_request", "user")
STATUSES = ("open", "reviewing", "resolved", "dismissed")
REPORT_LIMIT = (10, 24 * 60 * 60)   # reports per user per day
OWNER_COLUMN = {"offer": "supplier_id", "food_request": "distributor_id", "volunteer_request": "poster_id"}


def _parse_target(raw):
    try:
        kind, tid = (raw or "").split(":", 1)
        if kind in TARGET_TYPES:
            return kind, int(tid)
    except ValueError:
        pass
    abort(404)


def _target(kind, tid):
    """(title, url, reported user id) for something the current user may report; 404 otherwise."""
    if kind == "user":
        user = query("SELECT * FROM users WHERE id = ?", (tid,), one=True)
        if user is None or user["role"] == "admin" or user["id"] == g.user["id"]:
            abort(404)
        return user["org_name"] or user["name"], url_for("main.user_profile", user_id=tid), tid
    info = _ref_info(kind, tid)
    if info is None or not _can_view_ref(kind, info[0]):
        abort(404)
    owner = info[0][OWNER_COLUMN[kind]]
    if owner == g.user["id"]:
        abort(404)   # nothing to report about your own post
    return info[1], info[2], owner


@bp.route("/report", methods=("GET", "POST"))
@login_required
def new_report():
    if g.user["role"] == "admin":
        abort(404)
    raw = request.values.get("target", "")
    kind, tid = _parse_target(raw)
    title, url, reported_user = _target(kind, tid)
    values = {"category": "", "details": ""}
    if request.method == "POST":
        values = {"category": request.form.get("category", ""), "details": request.form.get("details", "").strip()}
        errors = []
        if values["category"] not in CATEGORIES:
            errors.append("Choose what kind of problem this is.")
        if not 10 <= len(values["details"]) <= 2000:
            errors.append("Describe what happened in 10 to 2000 characters.")
        key = f"report:user:{g.user['id']}"
        if over_limit(key, *REPORT_LIMIT):
            errors.append("You've sent a lot of reports today. Please try again tomorrow.")
        duplicate = query("""SELECT 1 FROM reports WHERE reporter_id = ? AND target_type = ? AND target_id = ?
                             AND status IN ('open', 'reviewing')""", (g.user["id"], kind, tid), one=True)
        if duplicate:
            flash("You've already reported this. Our admins are looking into it.", "info")
            return redirect(url)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            record_attempt(key)
            execute("""INSERT INTO reports (reporter_id, reported_user_id, target_type, target_id, category, details)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (g.user["id"], reported_user, kind, tid, values["category"], values["details"]))
            flash("Thank you. Your report was sent to the EcoServing admins, who will review it.", "success")
            return redirect(url)
    return render_template("reports/new.html", target=raw, kind=kind, title=title, url=url,
                           values=values, categories=CATEGORIES)


# ---------------------------------------------------------------------------
# Admin review
# ---------------------------------------------------------------------------

@bp.app_template_global()
def open_report_count():
    return query("SELECT COUNT(*) AS n FROM reports WHERE status = 'open'", one=True)["n"]


def _target_summary(r):
    """Title and link of a reported item, as an admin sees it (works for removed items too)."""
    if r["target_type"] == "user":
        user = query("SELECT name, org_name FROM users WHERE id = ?", (r["target_id"],), one=True)
        return (user["org_name"] or user["name"] if user else "(deleted user)",
                url_for("main.user_profile", user_id=r["target_id"]) if user else None)
    info = _ref_info(r["target_type"], r["target_id"])
    return (info[1], info[2]) if info else ("(deleted post)", None)


@bp.route("/admin/reports")
@role_required("admin")
def admin_reports():
    status = request.args.get("status", "open")
    where, args = ("", ()) if status == "all" else ("WHERE r.status = ?", (status if status in STATUSES else "open",))
    rows = query(
        f"""SELECT r.*, rp.name AS reporter_name, rp.email AS reporter_email,
                   u.name AS reported_name, u.org_name AS reported_org, u.email AS reported_email,
                   u.suspended_at AS reported_suspended, u.role AS reported_role,
                   (SELECT COUNT(*) FROM reports x WHERE x.reported_user_id = r.reported_user_id) AS reports_against
            FROM reports r JOIN users rp ON rp.id = r.reporter_id
            LEFT JOIN users u ON u.id = r.reported_user_id
            {where} ORDER BY r.created_at DESC LIMIT 200""", args)
    items = [{"r": r, "target": _target_summary(r)} for r in rows]
    counts = {s: 0 for s in STATUSES}
    counts.update({row["status"]: row["n"] for row in query("SELECT status, COUNT(*) AS n FROM reports GROUP BY status")})
    return render_template("admin/reports.html", items=items, status=status, counts=counts,
                           categories=CATEGORIES, statuses=STATUSES)


@bp.route("/admin/reports/<int:report_id>", methods=("POST",))
@role_required("admin")
def update_report(report_id):
    r = query("SELECT * FROM reports WHERE id = ?", (report_id,), one=True)
    status = request.form.get("status", "")
    if r is None or status not in STATUSES:
        abort(404)
    note = request.form.get("admin_note", "").strip()[:2000] or None
    execute("UPDATE reports SET status = ?, admin_note = ?, handled_by = ?, handled_at = ? WHERE id = ?",
            (status, note, g.user["id"], now_str(), report_id))
    flash(f"Report #{report_id} marked {status}.", "success")
    return redirect(url_for("reports.admin_reports", status=request.args.get("back", "open")))


TAKEDOWN = {
    "offer": "UPDATE food_offers SET status = 'cancelled' WHERE id = ? AND status IN ('available', 'claimed')",
    "food_request": "UPDATE food_requests SET status = 'closed' WHERE id = ? AND status IN ('open', 'pledged')",
    "volunteer_request": "UPDATE volunteer_requests SET status = 'closed' WHERE id = ? AND status != 'closed'",
}


@bp.route("/admin/reports/<int:report_id>/takedown", methods=("POST",))
@role_required("admin")
def takedown(report_id):
    r = query("SELECT * FROM reports WHERE id = ?", (report_id,), one=True)
    if r is None or r["target_type"] not in TAKEDOWN:
        abort(404)
    execute(TAKEDOWN[r["target_type"]], (r["target_id"],))
    flash("The reported post was taken down (cancelled / closed).", "success")
    return redirect(url_for("reports.admin_reports", status=request.args.get("back", "open")))


@bp.route("/admin/users/<int:user_id>/<action>", methods=("POST",))
@role_required("admin")
def suspend(user_id, action):
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if user is None or user["role"] == "admin" or action not in ("suspend", "unsuspend"):
        abort(404)
    if action == "suspend":
        reason = request.form.get("reason", "").strip()[:500] or "Suspended after a report."
        execute("UPDATE users SET suspended_at = ?, suspended_reason = ? WHERE id = ?", (now_str(), reason, user_id))
        # A suspended scammer's open posts come down with the account.
        for kind, sql in TAKEDOWN.items():
            col = OWNER_COLUMN[kind]
            table = {"offer": "food_offers", "food_request": "food_requests", "volunteer_request": "volunteer_requests"}[kind]
            for row in query(f"SELECT id FROM {table} WHERE {col} = ?", (user_id,)):
                execute(sql, (row["id"],))
        flash(f"{user['org_name'] or user['name']} is suspended and their open posts were taken down.", "success")
    else:
        execute("UPDATE users SET suspended_at = NULL, suspended_reason = NULL WHERE id = ?", (user_id,))
        flash(f"{user['org_name'] or user['name']} can log in again.", "success")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url)
                    else url_for("reports.admin_reports"))
