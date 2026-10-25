"""Who can see which posts. Kept in one place so list pages, detail pages and
claim actions all apply the same rules."""

from .db import now_str


def offer_visibility_clause(user):
    """SQL fragment (and args) restricting food_offers `o` to those `user` may see."""
    role = user["role"]
    if role == "admin":
        return "1=1", ()
    if role == "supplier":
        return "o.supplier_id = ?", (user["id"],)
    if role == "distributor":
        flag = "o.visible_distributors = 1"
    elif role == "volunteer":
        flag = "o.visible_volunteers = 1"
    else:  # consumer: only small offers suited to individual pickup
        flag = "o.visible_consumers = 1 AND o.size = 'small'"
    # Anyone who already claimed an offer keeps access to it.
    return f"(({flag}) OR o.claimed_by = ?)", (user["id"],)


def can_view_offer(user, offer):
    if user["role"] == "admin" or offer["supplier_id"] == user["id"] or offer["claimed_by"] == user["id"]:
        return True
    role = user["role"]
    if role == "distributor":
        return bool(offer["visible_distributors"])
    if role == "volunteer":
        return bool(offer["visible_volunteers"])
    if role == "consumer":
        return bool(offer["visible_consumers"]) and offer["size"] == "small"
    return False


def offer_is_expired(offer):
    return offer["status"] == "available" and offer["pickup_deadline"] < now_str()


def can_claim_offer(user, offer):
    from .helpers import is_verified
    return (user["role"] in ("distributor", "volunteer", "consumer")
            and offer["supplier_id"] != user["id"]
            and offer["status"] == "available"
            and not offer_is_expired(offer)
            and can_view_offer(user, offer)
            and is_verified(user))
