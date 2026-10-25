"""End-to-end tests using Flask's test client. Run: python -m unittest discover tests"""

import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO

from foodrelay import create_app
from foodrelay.db import init_db


def future(hours):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


class FoodRelayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = create_app({
            "TESTING": True,
            "DATABASE": os.path.join(self.tmp, "test.sqlite"),
            "UPLOAD_FOLDER": os.path.join(self.tmp, "uploads"),
        })
        os.makedirs(self.app.config["UPLOAD_FOLDER"], exist_ok=True)
        with self.app.app_context():
            init_db()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers -------------------------------------------------------------
    def client_for(self, role, email=None, org="Org"):
        c = self.app.test_client()
        email = email or f"{role}@example.test"
        self.post(c, "/register", role=role, name=role.title(), email=email, org_name=org,
                  password="password123", confirm="password123", city="Springfield")
        return c

    def csrf(self, c):
        html = c.get("/").get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, c, url, follow=True, **data):
        data["_csrf"] = self.csrf(c)
        return c.post(url, data=data, follow_redirects=follow)

    def verify(self, distributor_email):
        with self.app.app_context():
            from foodrelay.db import execute
            execute("UPDATE users SET verification_status = 'verified' WHERE email = ?", (distributor_email,))

    def make_offer(self, supplier, **overrides):
        data = dict(title="Bread", description="Fresh loaves", food_type="Bakery & bread", quantity="10",
                    size="small", location="1 Main St", city="Springfield", pickup_deadline=future(3),
                    visible_distributors="1")
        data.update(overrides)
        r = self.post(supplier, "/offers/new", follow=False, **data)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:2000])
        return int(r.headers["Location"].rsplit("/", 1)[1])

    # -- tests ---------------------------------------------------------------
    def test_public_pages(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/").status_code, 200)
        for role in ("supplier", "distributor", "volunteer", "consumer"):
            r = c.get(f"/learn/{role}")
            self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/learn/nobody").status_code, 404)

    def test_csrf_required(self):
        c = self.app.test_client()
        r = c.post("/login", data={"email": "x@y.z", "password": "x"})
        self.assertEqual(r.status_code, 400)

    def test_register_login_and_dashboards(self):
        for role in ("supplier", "distributor", "volunteer", "consumer"):
            c = self.client_for(role)
            r = c.get("/dashboard")
            self.assertEqual(r.status_code, 200, role)
        c = self.app.test_client()
        r = self.post(c, "/login", email="supplier@example.test", password="password123")
        self.assertIn("Supplier dashboard", r.get_data(as_text=True))
        r = self.post(c, "/login", email="supplier@example.test", password="wrong")
        self.assertIn("Incorrect email or password", r.get_data(as_text=True))

    def test_offer_visibility_and_claim(self):
        supplier = self.client_for("supplier")
        dist = self.client_for("distributor")
        consumer = self.client_for("consumer")
        oid = self.make_offer(supplier)  # distributors only

        self.assertEqual(consumer.get(f"/offers/{oid}").status_code, 404)
        # Unverified distributor can see but not claim.
        self.assertIn("verified", dist.get(f"/offers/{oid}").get_data(as_text=True))
        self.post(dist, f"/offers/{oid}/claim")
        with self.app.app_context():
            from foodrelay.db import query
            self.assertEqual(query("SELECT status FROM food_offers WHERE id=?", (oid,), one=True)["status"], "available")

        self.verify("distributor@example.test")
        r = self.post(dist, f"/offers/{oid}/claim")
        self.assertIn("Claimed!", r.get_data(as_text=True))
        r = self.post(supplier, f"/offers/{oid}/complete")
        self.assertIn("picked up", r.get_data(as_text=True))

    def test_consumers_only_see_small_offers(self):
        supplier = self.client_for("supplier")
        consumer = self.client_for("consumer")
        r = self.post(supplier, "/offers/new", size="large", visible_consumers="1", title="Big", description="d",
                      food_type="Mixed", quantity="1", location="x", pickup_deadline=future(2))
        self.assertIn("Only small offers", r.get_data(as_text=True))
        oid = self.make_offer(supplier, visible_consumers="1", visible_distributors="")
        self.assertEqual(consumer.get(f"/offers/{oid}").status_code, 200)
        r = self.post(consumer, f"/offers/{oid}/claim")
        self.assertIn("Claimed!", r.get_data(as_text=True))

    def test_distributor_verification_flow(self):
        dist = self.client_for("distributor", org="Shelter")
        self.assertIn("Get verified", dist.get("/dashboard").get_data(as_text=True))
        self.post(dist, "/profile", name="D", org_name="Shelter", registration_number="CH-1")
        data = {"doc_type": "Food safety certificate", "document": (BytesIO(b"%PDF-1.4"), "cert.pdf"),
                "_csrf": self.csrf(dist)}
        dist.post("/profile/documents", data=data, content_type="multipart/form-data")
        r = self.post(dist, "/profile/submit-verification")
        self.assertIn("Submitted", r.get_data(as_text=True))

        with self.app.app_context():
            from foodrelay.db import execute
            from werkzeug.security import generate_password_hash
            execute("INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, 'A', 'admin')",
                    ("admin@example.test", generate_password_hash("password123")))
        admin = self.app.test_client()
        self.post(admin, "/login", email="admin@example.test", password="password123")
        page = admin.get("/admin/").get_data(as_text=True)
        self.assertIn("Shelter", page)
        self.assertIn("cert.pdf", page)
        self.post(admin, "/admin/distributors/1/verify")
        self.assertIn("Verified", dist.get("/dashboard").get_data(as_text=True))

    def test_food_request_and_volunteer_flow(self):
        dist = self.client_for("distributor")
        self.verify("distributor@example.test")
        supplier = self.client_for("supplier")
        vol = self.client_for("volunteer")

        r = self.post(dist, "/food-requests/new", title="Need bread", description="x", quantity="5",
                      location="Shelter", needed_by=future(10))
        self.assertIn("Food request posted", r.get_data(as_text=True))
        r = self.post(supplier, "/food-requests/1/pledge")
        self.assertIn("Pledged", r.get_data(as_text=True))

        r = self.post(supplier, "/volunteer/new", title="Pack bread", tasks="Pack", location="Bakery",
                      start_time=future(5), end_time=future(7), slots="1")
        self.assertIn("Volunteer request posted", r.get_data(as_text=True))
        self.post(vol, "/volunteer/1/apply", message="Happy to help")
        page = supplier.get("/volunteer/1").get_data(as_text=True)
        self.assertIn("Happy to help", page)
        self.post(supplier, "/volunteer/signups/1/accept")
        self.assertIn("Filled", supplier.get("/volunteer/1").get_data(as_text=True))

    def test_chat(self):
        supplier = self.client_for("supplier")
        dist = self.client_for("distributor")
        oid = self.make_offer(supplier)
        # Can't start a chat without a post reference.
        r = dist.get("/messages/with/1", follow_redirects=True)
        self.assertIn("Start a conversation from an offer", r.get_data(as_text=True))
        r = dist.get(f"/messages/with/1?ref=offer:{oid}")
        self.assertEqual(r.status_code, 302)
        cid = int(re.search(r"/messages/(\d+)", r.headers["Location"]).group(1))
        token = self.csrf(dist)
        r = dist.post(f"/api/messages/{cid}", json={"body": "Hi!", "ref": f"offer:{oid}"},
                      headers={"X-CSRF-Token": token})
        self.assertEqual(r.status_code, 200)
        self.assertIn("1", supplier.get("/dashboard").get_data(as_text=True))  # unread badge
        data = supplier.get(f"/api/messages/{cid}?after=0").get_json()
        self.assertEqual(data["messages"][0]["body"], "Hi!")
        self.assertIn(f"offer:{oid}", data["refs"])
        # A third user can't read it.
        other = self.client_for("consumer")
        self.assertEqual(other.get(f"/messages/{cid}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
