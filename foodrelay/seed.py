"""Demo data so every role has something to look at. Run: flask --app foodrelay seed

Accounts and posts are located around Minneapolis-St. Paul so the maps and routes work."""

from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from .db import execute

DEMO_PASSWORD = "foodrelay-demo"
MPLS, STP = "Minneapolis, MN", "St. Paul, MN"

# Demo places around the Twin Cities: (address, city, lat, lng). Businesses are fictional.
BAKERY = ("2400 Nicollet Ave", MPLS, 44.96012, -93.27795)
BISTRO = ("315 1st Ave N", MPLS, 44.98408, -93.27305)
SHELTER = ("900 E Franklin Ave", MPLS, 44.96275, -93.26095)
PANTRY = ("500 University Ave W", STP, 44.95580, -93.11700)
VOLUNTEER = ("1600 Grand Ave", STP, 44.94000, -93.16900)
CONSUMER = ("3000 Lyndale Ave S", MPLS, 44.94880, -93.28810)
EXTRA_REQUESTS = [  # more distributor drop-off points, so the dashboard map has several targets
    ("Senior center lunch boxes", ("2200 Minnehaha Ave", MPLS, 44.96010, -93.24120)),
    ("After-school snacks", ("1500 E Lake St", MPLS, 44.94855, -93.25290)),
    ("Family pantry restock", ("800 W Broadway Ave", MPLS, 44.99900, -93.29300)),
    ("Outreach van dinners", ("700 E 7th St", STP, 44.96010, -93.07520)),
    ("Weekend groceries", ("2600 Central Ave NE", MPLS, 45.01550, -93.24700)),
    ("Tenant association breakfast", ("1000 Payne Ave", STP, 44.97020, -93.07310)),
]


def _t(hours):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


def seed():
    pw = generate_password_hash(DEMO_PASSWORD)

    def user(email, name, role, place=None, org=None, status="not_required", reg=None, bio=None):
        address, city, lat, lng = place or (None, MPLS, None, None)
        return execute(
            """INSERT INTO users (email, password_hash, name, role, org_name, city, address, lat, lng,
                                  verification_status, registration_number, bio)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, pw, name, role, org, city, address, lat, lng, status, reg, bio))

    user("admin@foodrelay.test", "FoodRelay Admin", "admin")
    bakery = user("bakery@foodrelay.test", "Maria Lopez", "supplier", BAKERY, "Sunrise Bakery",
                  bio="Neighborhood bakery. We usually have bread left at closing.")
    bistro = user("bistro@foodrelay.test", "Tom Becker", "supplier", BISTRO, "Green Fork Bistro")
    shelter = user("shelter@foodrelay.test", "Aisha Khan", "distributor", SHELTER, "Harbor Street Shelter",
                   status="verified", reg="CH-204518", bio="Overnight shelter serving ~60 guests a night.")
    user("pantry@foodrelay.test", "Leo Park", "distributor", PANTRY, "Eastside Community Pantry",
         status="pending", reg="NP-778120")
    vol = user("volunteer@foodrelay.test", "Sam Rivera", "volunteer", VOLUNTEER, bio="Have a car and free evenings.")
    user("consumer@foodrelay.test", "Jordan Lee", "consumer", CONSUMER)

    offer_sql = """INSERT INTO food_offers (supplier_id, title, description, food_type, dietary_tags, quantity, size,
                       location, city, lat, lng, pickup_start, pickup_deadline, visible_distributors,
                       visible_consumers, status, claimed_by, claimed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    def offer(supplier, place, title, desc, food_type, tags, qty, size, start, deadline, dist, cons,
              status="available", claimed_by=None, claimed_at=None):
        address, city, lat, lng = place
        execute(offer_sql, (supplier, title, desc, food_type, tags, qty, size, address, city, lat, lng,
                            start, deadline, dist, cons, status, claimed_by, claimed_at))

    offer(bakery, BAKERY, "End-of-day bread & pastries", "Sourdough loaves, baguettes and croissants baked this morning.",
          "Bakery & bread", "vegetarian", "About 25 items", "medium", _t(1), _t(5), 1, 0)
    offer(bakery, BAKERY, "Box of 6 muffins", "Blueberry and banana muffins, individually wrapped.",
          "Bakery & bread", "vegetarian, contains nuts", "6 muffins", "small", _t(0), _t(3), 1, 1)
    offer(bistro, BISTRO, "Trays of roasted vegetable lasagna",
          "Three full catering trays left from a cancelled event. Kept refrigerated.",
          "Prepared meals", "vegetarian", "3 trays (~36 portions)", "large", _t(2), _t(20), 1, 0)
    offer(bistro, BISTRO, "Soup & salad portions", "Lentil soup (8 L) and mixed salad.",
          "Prepared meals", "vegan", "~20 portions", "medium", _t(-3), _t(4), 1, 0, "claimed", shelter, _t(-2))

    req_sql = """INSERT INTO food_requests (distributor_id, title, description, quantity, location, city, lat, lng,
                                            needed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    execute(req_sql, (shelter, "Breakfast items for weekend",
                      "Bread, eggs, fruit or cereal for Saturday and Sunday breakfast.",
                      "Enough for 60 people x 2 days", *SHELTER, _t(48)))
    for i, (title, place) in enumerate(EXTRA_REQUESTS):
        execute(req_sql, (shelter, title, "Any fresh or packaged food that's easy to hand out.",
                          f"{20 + 10 * i} portions", *place, _t(24 + 6 * i)))

    vol_sql = """INSERT INTO volunteer_requests (poster_id, title, tasks, requirements, location, city, lat, lng,
                                                  start_time, end_time, slots) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    v1 = execute(vol_sql, (shelter, "Evening food run",
                           "Pick up donations from 2-3 restaurants and bring them to the shelter.",
                           "Own car, valid driver's license", *SHELTER, _t(26), _t(29), 2))
    execute(vol_sql, (bakery, "Sort and pack leftover bread", "Bag bread into portions and label with date.",
                      "None, gloves provided", *BAKERY, _t(30), _t(32), 1))
    execute("INSERT INTO volunteer_signups (request_id, volunteer_id, message, status) VALUES (?, ?, ?, 'accepted')",
            (v1, vol, "I can drive, have a hatchback."))

    lo, hi = sorted((shelter, bistro))
    cid = execute("INSERT INTO conversations (user_low, user_high) VALUES (?, ?)", (lo, hi))
    execute("INSERT INTO messages (conversation_id, sender_id, body, ref_type, ref_id) VALUES (?, ?, ?, 'offer', 4)",
            (cid, shelter, "Hi Tom, we claimed the soup. Can we come by at 5pm?"))
    execute("INSERT INTO messages (conversation_id, sender_id, body) VALUES (?, ?, ?)",
            (cid, bistro, "5pm works. Ring the bell at the loading bay."))
