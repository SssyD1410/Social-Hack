"""Direct messages between users, started from an offer or request."""

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .db import execute, now_str, query
from .helpers import login_required
from .visibility import can_view_offer

bp = Blueprint("chat", __name__)

REF_TYPES = {"offer", "food_request", "volunteer_request"}


def _parse_ref(raw):
    """'offer:12' -> ('offer', 12); anything invalid -> (None, None)."""
    try:
        kind, rid = (raw or "").split(":", 1)
        if kind in REF_TYPES:
            return kind, int(rid)
    except ValueError:
        pass
    return None, None


def _ref_info(kind, rid):
    """Return (title, url, set of user ids involved in the post), or None."""
    if kind == "offer":
        row = query("SELECT * FROM food_offers WHERE id = ?", (rid,), one=True)
        if row:
            return row, row["title"], url_for("posts.offer", offer_id=rid), {row["supplier_id"], row["claimed_by"]}
    elif kind == "food_request":
        row = query("SELECT * FROM food_requests WHERE id = ?", (rid,), one=True)
        if row:
            return row, row["title"], url_for("posts.food_request", req_id=rid), {row["distributor_id"], row["pledged_by"]}
    elif kind == "volunteer_request":
        row = query("SELECT * FROM volunteer_requests WHERE id = ?", (rid,), one=True)
        if row:
            vols = {r["volunteer_id"] for r in query(
                "SELECT volunteer_id FROM volunteer_signups WHERE request_id = ?", (rid,))}
            return row, row["title"], url_for("posts.volunteer_request", req_id=rid), {row["poster_id"], *vols}
    return None


def _can_view_ref(kind, row):
    u = g.user
    if kind == "offer":
        return can_view_offer(u, row)
    if kind == "food_request":
        return u["role"] in ("supplier", "distributor", "volunteer", "admin")
    return True


def _get_conversation(cid):
    c = query("SELECT * FROM conversations WHERE id = ?", (cid,), one=True)
    if c is None or g.user["id"] not in (c["user_low"], c["user_high"]):
        abort(404)
    return c


def _find_conversation(a, b):
    lo, hi = sorted((a, b))
    return query("SELECT * FROM conversations WHERE user_low = ? AND user_high = ?", (lo, hi), one=True)


def _message_dict(m):
    return {"id": m["id"], "sender_id": m["sender_id"], "body": m["body"], "created_at": m["created_at"],
            "ref_type": m["ref_type"], "ref_id": m["ref_id"], "mine": m["sender_id"] == g.user["id"]}


@bp.route("/messages")
@login_required
def inbox():
    uid = g.user["id"]
    convs = query(
        """SELECT c.id, c.updated_at, u.id AS other_id, u.name AS other_name, u.org_name AS other_org,
                  u.role AS other_role,
                  (SELECT body FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_body,
                  (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id AND sender_id != ? AND read_at IS NULL) AS unread_n
           FROM conversations c
           JOIN users u ON u.id = CASE WHEN c.user_low = ? THEN c.user_high ELSE c.user_low END
           WHERE c.user_low = ? OR c.user_high = ? ORDER BY c.updated_at DESC""", (uid, uid, uid, uid))
    return render_template("chat/inbox.html", convs=convs)


@bp.route("/messages/with/<int:user_id>")
@login_required
def start(user_id):
    """Open (or create) a conversation with another user about a specific post."""
    me = g.user["id"]
    other = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if other is None or user_id == me:
        abort(404)
    ref = request.args.get("ref", "")
    existing = _find_conversation(me, user_id)
    kind, rid = _parse_ref(ref)
    info = _ref_info(kind, rid) if kind else None
    if existing is None:
        # New conversations must come from a post that both people are part of
        # (the poster, or someone who can see it and is contacting the poster).
        if info is None or not _can_view_ref(kind, info[0]):
            flash("Start a conversation from an offer or request.", "error")
            return redirect(url_for("chat.inbox"))
        involved = info[3]
        if me not in involved and user_id not in involved:
            abort(403)
        lo, hi = sorted((me, user_id))
        cid = execute("INSERT INTO conversations (user_low, user_high) VALUES (?, ?)", (lo, hi))
    else:
        cid = existing["id"]
    return redirect(url_for("chat.conversation", cid=cid, ref=ref if info else None))


@bp.route("/messages/<int:cid>", methods=("GET", "POST"))
@login_required
def conversation(cid):
    c = _get_conversation(cid)
    me = g.user["id"]
    if request.method == "POST":
        _send(c, request.form.get("body", ""), request.form.get("ref", ""))
        return redirect(url_for("chat.conversation", cid=cid))

    other_id = c["user_high"] if c["user_low"] == me else c["user_low"]
    other = query("SELECT * FROM users WHERE id = ?", (other_id,), one=True)
    execute("UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL",
            (now_str(), cid, me))
    msgs = query("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (cid,))

    # Titles/links for posts referenced in this conversation.
    refs = {}
    for m in msgs:
        key = (m["ref_type"], m["ref_id"])
        if m["ref_type"] and key not in refs:
            info = _ref_info(*key)
            refs[key] = (info[1], info[2]) if info else ("(removed)", None)
    ref = request.args.get("ref", "")
    kind, rid = _parse_ref(ref)
    pending_ref = None
    if kind and (info := _ref_info(kind, rid)) and _can_view_ref(kind, info[0]):
        pending_ref = {"key": ref, "title": info[1], "url": info[2]}
    return render_template("chat/conversation.html", c=c, other=other, msgs=msgs, refs=refs,
                           pending_ref=pending_ref)


def _send(c, body, ref):
    body = body.strip()
    if not body:
        return None
    if len(body) > 4000:
        body = body[:4000]
    kind, rid = _parse_ref(ref)
    if kind and not _ref_info(kind, rid):
        kind = rid = None
    ts = now_str()
    mid = execute("INSERT INTO messages (conversation_id, sender_id, body, ref_type, ref_id, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (c["id"], g.user["id"], body, kind, rid, ts))
    execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, c["id"]))
    return query("SELECT * FROM messages WHERE id = ?", (mid,), one=True)


@bp.route("/api/messages/<int:cid>", methods=("GET", "POST"))
@login_required
def api_messages(cid):
    c = _get_conversation(cid)
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        m = _send(c, str(data.get("body", "")), str(data.get("ref", "")))
        if m is None:
            return jsonify(error="Message is empty."), 400
        return jsonify(message=_message_dict(m))
    after = request.args.get("after", 0, type=int)
    msgs = query("SELECT * FROM messages WHERE conversation_id = ? AND id > ? ORDER BY id", (cid, after))
    execute("UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL",
            (now_str(), cid, g.user["id"]))
    refs = {}
    for m in msgs:
        if m["ref_type"] and (info := _ref_info(m["ref_type"], m["ref_id"])):
            refs[f"{m['ref_type']}:{m['ref_id']}"] = {"title": info[1], "url": info[2]}
    return jsonify(messages=[_message_dict(m) for m in msgs], refs=refs)
