"""Admin tools: verifying distributor organizations."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import execute, query
from .helpers import role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@role_required("admin")
def index():
    status = request.args.get("status", "pending")
    if status not in ("pending", "verified", "rejected", "unverified"):
        status = "pending"
    distributors = query("SELECT * FROM users WHERE role = 'distributor' AND verification_status = ? "
                         "ORDER BY created_at", (status,))
    docs = {}
    for d in distributors:
        docs[d["id"]] = query("SELECT * FROM verification_documents WHERE user_id = ? ORDER BY uploaded_at",
                              (d["id"],))
    counts = {r["role"]: r["n"] for r in query("SELECT role, COUNT(*) AS n FROM users GROUP BY role")}
    return render_template("admin/index.html", distributors=distributors, docs=docs, status=status, counts=counts)


@bp.route("/distributors/<int:user_id>/<decision>", methods=("POST",))
@role_required("admin")
def decide(user_id, decision):
    user = query("SELECT * FROM users WHERE id = ? AND role = 'distributor'", (user_id,), one=True)
    if user is None or decision not in ("verify", "reject"):
        abort(404)
    note = request.form.get("note", "").strip() or None
    execute("UPDATE users SET verification_status = ?, verification_note = ? WHERE id = ?",
            ("verified" if decision == "verify" else "rejected", note, user_id))
    flash(f"{user['org_name'] or user['name']} {'verified' if decision == 'verify' else 'rejected'}.", "success")
    return redirect(url_for("admin.index"))
