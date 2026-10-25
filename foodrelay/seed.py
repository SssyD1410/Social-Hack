"""Demo data so every role has something to look at. Run: flask --app foodrelay seed"""

from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from .db import execute

DEMO_PASSWORD = "foodrelay-demo"


def _t(hours):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


def seed():
    pw = generate_password_hash(DEMO_PASSWORD)

    def user(email, name, role, org=None, city="Springfield", address=None, status="not_required", reg=None, bio=None):
        return execute(
            """INSERT INTO users (email, password_hash, name, role, org_name, city, address, verification_status,
                                  registration_number, bio) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, pw, name, role, org, city, address, status, reg, bio))

    user("admin@foodrelay.test", "FoodRelay Admin", "admin")
    bakery = user("bakery@foodrelay.test", "Maria Lopez", "supplier", "Sunrise Bakery",
                  address="12 Main St", bio="Neighborhood bakery. We usually have bread left at closing.")
    bistro = user("bistro@foodrelay.test", "Tom Becker", "supplier", "Green Fork Bistro", address="88 Oak Ave")
    shelter = user("shelter@foodrelay.test", "Aisha Khan", "distributor", "Harbor Street Shelter",
                   address="5 Harbor St", status="verified", reg="CH-204518",
                   bio="Overnight shelter serving ~60 guests a night.")
    user("pantry@foodrelay.test", "Leo Park", "distributor", "Eastside Community Pantry",
         address="301 East Rd", status="pending", reg="NP-778120")
    vol = user("volunteer@foodrelay.test", "Sam Rivera", "volunteer", bio="Have a car and free evenings.")
    user("consumer@foodrelay.test", "Jordan Lee", "consumer")

    offer_sql = """INSERT INTO food_offers (supplier_id, title, description, food_type, dietary_tags, quantity, size,
                       location, city, pickup_start, pickup_deadline, visible_distributors, visible_volunteers,
                       visible_consumers, status, claimed_by, claimed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Springfield', ?, ?, ?, ?, ?, ?, ?, ?)"""
    execute(offer_sql, (bakery, "End-of-day bread & pastries", "Sourdough loaves, baguettes and croissants baked this morning.",
                        "Bakery & bread", "vegetarian", "About 25 items", "medium", "12 Main St (back door)",
                        _t(1), _t(5), 1, 1, 0, "available", None, None))
    execute(offer_sql, (bakery, "Box of 6 muffins", "Blueberry and banana muffins, individually wrapped.",
                        "Bakery & bread", "vegetarian, contains nuts", "6 muffins", "small", "12 Main St (front counter)",
                        _t(0), _t(3), 1, 1, 1, "available", None, None))
    execute(offer_sql, (bistro, "Trays of roasted vegetable lasagna", "Three full catering trays left from a cancelled event. Kept refrigerated.",
                        "Prepared meals", "vegetarian", "3 trays (~36 portions)", "large", "88 Oak Ave, loading bay",
                        _t(2), _t(20), 1, 0, 0, "available", None, None))
    execute(offer_sql, (bistro, "Soup & salad portions", "Lentil soup (8 L) and mixed salad.",
                        "Prepared meals", "vegan", "~20 portions", "medium", "88 Oak Ave",
                        _t(-3), _t(4), 1, 1, 0, "claimed", shelter, _t(-2)))

    execute("""INSERT INTO food_requests (distributor_id, title, description, quantity, location, city, needed_by)
               VALUES (?, ?, ?, ?, ?, 'Springfield', ?)""",
            (shelter, "Breakfast items for weekend", "Bread, eggs, fruit or cereal for Saturday and Sunday breakfast.",
             "Enough for 60 people x 2 days", "5 Harbor St", _t(48)))

    v1 = execute("""INSERT INTO volunteer_requests (poster_id, title, tasks, requirements, location, city,
                                                     start_time, end_time, slots)
                    VALUES (?, ?, ?, ?, ?, 'Springfield', ?, ?, ?)""",
                 (shelter, "Evening food run", "Pick up donations from 2-3 restaurants and bring them to the shelter.",
                  "Own car, valid driver's license", "5 Harbor St", _t(26), _t(29), 2))
    execute("""INSERT INTO volunteer_requests (poster_id, title, tasks, requirements, location, city,
                                                start_time, end_time, slots)
               VALUES (?, ?, ?, ?, ?, 'Springfield', ?, ?, ?)""",
            (bakery, "Sort and pack leftover bread", "Bag bread into portions and label with date.",
             "None, gloves provided", "12 Main St", _t(30), _t(32), 1))
    execute("INSERT INTO volunteer_signups (request_id, volunteer_id, message) VALUES (?, ?, ?)",
            (v1, vol, "I can drive, have a hatchback."))

    lo, hi = sorted((shelter, bistro))
    cid = execute("INSERT INTO conversations (user_low, user_high) VALUES (?, ?)", (lo, hi))
    execute("INSERT INTO messages (conversation_id, sender_id, body, ref_type, ref_id) VALUES (?, ?, ?, 'offer', 4)",
            (cid, shelter, "Hi Tom, we claimed the soup. Can we come by at 5pm?"))
    execute("INSERT INTO messages (conversation_id, sender_id, body) VALUES (?, ?, ?)",
            (cid, bistro, "5pm works. Ring the bell at the loading bay."))
