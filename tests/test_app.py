"""End-to-end tests using Flask's test client. Run: python -m unittest discover tests"""

import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO

from ecoserving import create_app
from ecoserving.db import init_db


def future(hours):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


class EcoServingTest(unittest.TestCase):
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
            from ecoserving.db import execute
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
        page = c.get("/learn").get_data(as_text=True)
        self.assertIn("EcoServing separates users into four roles", page)
        for role in ("supplier", "distributor", "volunteer", "consumer"):
            self.assertIn(f'id="panel-{role}"', page)
        self.assertNotIn("Other roles", page)
        home = c.get("/").get_data(as_text=True)
        self.assertIn('href="/learn"', home)          # "Find your role" + single learn-more link
        self.assertNotIn("offers rescued", home)      # stats are commented out
        self.assertNotIn("How it works</a>", home)    # removed from the header

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
            from ecoserving.db import query
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
            from ecoserving.db import execute
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

    def test_volunteers_cannot_see_offers(self):
        supplier = self.client_for("supplier")
        vol = self.client_for("volunteer")
        oid = self.make_offer(supplier, visible_volunteers="1")
        self.assertEqual(vol.get(f"/offers/{oid}", follow_redirects=False).status_code, 302)
        self.assertEqual(vol.get("/offers", follow_redirects=False).status_code, 302)
        dash = vol.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("Food offers</a>", dash)
        self.assertNotIn("Bread", dash)

    def test_cancel_and_release_buttons_submit_without_native_confirm(self):
        supplier = self.client_for("supplier")
        oid = self.make_offer(supplier)
        page = supplier.get(f"/offers/{oid}").get_data(as_text=True)
        self.assertNotIn("return confirm(", page)
        self.assertIn('data-confirm="Click again to confirm"', page)
        r = self.post(supplier, f"/offers/{oid}/cancel")
        self.assertIn("Offer cancelled", r.get_data(as_text=True))

    def test_cant_make_it_relists_volunteer_spot(self):
        supplier = self.client_for("supplier")
        vol = self.client_for("volunteer")
        self.post(supplier, "/volunteer/new", title="Pack", tasks="Pack", location="Bakery",
                  start_time=future(5), end_time=future(7), slots="1")
        self.post(vol, "/volunteer/1/apply")
        self.post(supplier, "/volunteer/signups/1/accept")
        self.assertIn("Filled", vol.get("/volunteer/1").get_data(as_text=True))
        self.assertIn("I can&#39;t make it", vol.get("/volunteer/1").get_data(as_text=True))
        r = self.post(vol, "/volunteer/1/withdraw")
        page = r.get_data(as_text=True)
        self.assertIn("re-listed", page)
        self.assertIn("Open", page)

    def test_own_volunteer_requests_stand_out(self):
        supplier = self.client_for("supplier")
        other = self.client_for("supplier", email="other@example.test")
        for c, title in ((other, "Theirs"), (supplier, "Mine")):
            self.post(c, "/volunteer/new", title=title, tasks="t", location="x",
                      start_time=future(5), end_time=future(7), slots="1")
        page = supplier.get("/volunteer").get_data(as_text=True)
        self.assertIn("own-post", page)
        self.assertLess(page.index("Mine"), page.index("Theirs"))  # own requests listed first
        self.assertEqual(page.count("own-post"), 1)

    def test_dashboard_map_top_six_nearest(self):
        dist = self.client_for("distributor")
        self.verify("distributor@example.test")
        for i in range(8):  # 8 requests, increasingly far from the supplier
            self.post(dist, "/food-requests/new", title=f"Req {i}", description="x", quantity="1",
                      location="x", needed_by=future(10), lat=str(40 + i * 0.1), lng="-89")
        supplier = self.client_for("supplier", email="s2@example.test")
        self.post(supplier, "/profile", name="S", org_name="Org", lat="40.0", lng="-89.0")
        with self.app.test_request_context():
            from flask import g
            from ecoserving.db import now_str, query
            from ecoserving.main import _dashboard_map
            g.user = query("SELECT * FROM users WHERE email = 's2@example.test'", one=True)
            data = _dashboard_map(g.user, now_str())
        self.assertEqual(len(data["targets"]), 6)
        self.assertEqual(data["total"], 8)
        self.assertEqual([t["title"] for t in data["targets"]], [f"Req {i}" for i in range(6)])
        page = supplier.get("/dashboard").get_data(as_text=True)
        self.assertIn("Showing only the top 6", page)
        self.assertIn("dashboard-map", page)
        self.assertIn("request-map", supplier.get("/food-requests/1").get_data(as_text=True))

    def test_logout_is_on_profile(self):
        c = self.client_for("consumer")
        self.assertNotIn("Log out", c.get("/dashboard").get_data(as_text=True))
        self.assertIn("Log out", c.get("/profile").get_data(as_text=True))

    def test_back_buttons(self):
        supplier = self.client_for("supplier")
        oid = self.make_offer(supplier)
        for url in (f"/offers/{oid}", "/offers/new", f"/offers/{oid}/edit", "/volunteer/new", "/users/1", "/learn"):
            self.assertIn("data-back", supplier.get(url).get_data(as_text=True), url)

    def test_free_maps(self):
        page = self.client_for("supplier").get("/dashboard").get_data(as_text=True)
        self.assertIn("leaflet", page)
        self.assertNotIn("mapkit", page.lower())
        self.assertNotIn("googleapis", page)

    def test_no_emoji_and_icons_render(self):
        emoji = re.compile(r"[\U0001F000-\U0001FFFF⌀-⏿☀-➿️]")
        supplier = self.client_for("supplier")
        oid = self.make_offer(supplier)
        anon = self.app.test_client()
        pages = [(anon, "/"), (anon, "/learn"), (anon, "/register"),
                 (supplier, "/dashboard"), (supplier, f"/offers/{oid}"), (supplier, "/profile")]
        for c, url in pages:
            html = c.get(url).get_data(as_text=True)
            self.assertIsNone(emoji.search(html), f"emoji on {url}: {emoji.findall(html)[:3]}")
            self.assertIn("/static/logo.svg", html, url)
            if url in ("/", "/learn", "/dashboard"):
                self.assertIn("icons.svg#", html, url)
        with anon.get("/favicon.ico") as r:
            self.assertEqual(r.status_code, 200)

    def test_photos_on_offers_and_requests(self):
        supplier = self.client_for("supplier")
        # No photo: a stock photo of the food type, with its alt text.
        oid = self.make_offer(supplier)
        page = supplier.get(f"/offers/{oid}").get_data(as_text=True)
        self.assertRegex(page, r'class="detail-photo"><img src="/static/photos/(fresh-bread|bakery-shelves|bakery-counter)\.jpg"')
        self.assertIn('class="post-photo"', supplier.get("/offers").get_data(as_text=True))
        # An uploaded photo replaces it and is served to logged-in users only.
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
        r = self.post(supplier, "/offers/new", follow=False, title="Soup", description="Lentil soup",
                      food_type="Prepared meals", quantity="8", size="medium", location="1 Main St",
                      pickup_deadline=future(3), visible_distributors="1", photo=(BytesIO(png), "soup.png"))
        self.assertEqual(r.status_code, 302)
        page = supplier.get(r.headers["Location"]).get_data(as_text=True)
        name = re.search(r'src="/photos/([0-9a-f]{32}\.png)"', page).group(1)
        with supplier.get(f"/photos/{name}") as r:
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self.app.test_client().get(f"/photos/{name}").status_code, 302)
        # Files that aren't images are refused.
        r = self.post(supplier, "/offers/new", title="Soup", description="x", food_type="Prepared meals",
                      quantity="8", location="1 Main St", pickup_deadline=future(3), visible_distributors="1",
                      photo=(BytesIO(b"<script>"), "soup.png"))
        self.assertIn("Photos must be JPG, PNG or WebP images.", r.get_data(as_text=True))
        # Food and volunteer requests get photos too; a request's words pick a fitting stock photo.
        dist = self.client_for("distributor")
        self.verify("distributor@example.test")
        self.post(dist, "/food-requests/new", title="Bread for breakfast", description="Loaves", quantity="20",
                  location="2 Main St", needed_by=future(5))
        self.assertRegex(dist.get("/food-requests").get_data(as_text=True),
                         r'class="post-photo"><img src="/static/photos/sm/(fresh-bread|bakery-shelves|bakery-counter)\.jpg"')
        self.post(dist, "/volunteer/new", title="Drivers", tasks="Drive", location="2 Main St",
                  start_time=future(2), end_time=future(4), slots="1")
        self.assertIn('class="post-photo"', dist.get("/volunteer").get_data(as_text=True))

    def test_distributors_only_see_their_own_requests(self):
        d1 = self.client_for("distributor", "d1@example.test", org="Shelter One")
        d2 = self.client_for("distributor", "d2@example.test", org="Shelter Two")
        self.verify("d1@example.test"); self.verify("d2@example.test")
        r = self.post(d1, "/food-requests/new", follow=False, title="Rice for One", description="x",
                      quantity="5", location="1 Main St", needed_by=future(5))
        rid1 = int(r.headers["Location"].rsplit("/", 1)[1])
        self.post(d2, "/food-requests/new", title="Beans for Two", description="x",
                  quantity="5", location="2 Main St", needed_by=future(5))
        page = d1.get("/food-requests").get_data(as_text=True)
        self.assertIn("Rice for One", page)
        self.assertNotIn("Beans for Two", page)
        self.assertEqual(d2.get(f"/food-requests/{rid1}").status_code, 404)
        self.assertEqual(d1.get(f"/food-requests/{rid1}").status_code, 200)
        supplier = self.client_for("supplier")      # suppliers still see every open request
        page = supplier.get("/food-requests").get_data(as_text=True)
        self.assertIn("Rice for One", page)
        self.assertIn("Beans for Two", page)

    def test_homepage_photos_and_credits(self):
        anon = self.app.test_client()
        home = anon.get("/").get_data(as_text=True)
        self.assertGreaterEqual(home.count("/static/photos/"), 8)
        self.assertIn("prefers-reduced-motion", home)
        credits = anon.get("/credits").get_data(as_text=True)
        self.assertIn("Wikimedia Commons", credits)
        self.assertIn("Photo credits", home)
        with self.app.app_context():
            from ecoserving.photos import STOCK_BY_TYPE, stock_credits
            from ecoserving.helpers import FOOD_TYPES
            self.assertEqual(set(STOCK_BY_TYPE), set(FOOD_TYPES))
            for names in STOCK_BY_TYPE.values():
                for name in names:
                    self.assertIn(name, stock_credits())
                    self.assertTrue(os.path.exists(os.path.join(self.app.static_folder, "photos", "sm", name + ".jpg")))

    def test_secret_key_and_create_admin(self):
        key = self.app.config["SECRET_KEY"]
        self.assertTrue(key and key != "dev-change-me" and len(key) >= 32)
        self.assertTrue(os.path.exists(os.path.join(self.app.instance_path, "secret_key")))
        runner = self.app.test_cli_runner()
        r = runner.invoke(args=["create-admin", "--email", "boss@example.test", "--name", "Boss",
                                "--password", "longpassword"])
        self.assertIn("Created admin", r.output)
        r = runner.invoke(args=["create-admin", "--email", "boss@example.test", "--name", "Boss",
                                "--password", "longpassword"])
        self.assertIn("already exists", r.output)
        c = self.app.test_client()
        page = self.post(c, "/login", email="boss@example.test", password="longpassword").get_data(as_text=True)
        self.assertIn('href="/admin', page)

    def test_logo_and_share_tags(self):
        home = self.app.test_client().get("/").get_data(as_text=True)
        self.assertIn('class="logo-mark" src="/static/logo.svg"', home)
        self.assertIn('property="og:image" content="http://localhost/static/share/og-image.png"', home)
        self.assertIn('name="twitter:card" content="summary_large_image"', home)
        for path in ("logo.svg", "share/og-image.png", "share/twitter-image.png", "favicon/favicon.ico"):
            self.assertTrue(os.path.exists(os.path.join(self.app.static_folder, path)), path)

    # -- security --------------------------------------------------------------
    def admin_client(self):
        with self.app.app_context():
            from ecoserving.db import execute
            from werkzeug.security import generate_password_hash
            execute("INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, 'Admin', 'admin')",
                    ("root@example.test", generate_password_hash("password123")))
        admin = self.app.test_client()
        self.post(admin, "/login", email="root@example.test", password="password123")
        return admin

    def test_login_redirect_stays_on_site(self):
        self.client_for("consumer")
        for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "/\t/evil.example"):
            c = self.app.test_client()
            r = self.post(c, "/login?next=" + bad, follow=False, email="consumer@example.test", password="password123")
            self.assertEqual(r.headers["Location"], "/dashboard", bad)
        c = self.app.test_client()
        r = self.post(c, "/login?next=/offers", follow=False, email="consumer@example.test", password="password123")
        self.assertEqual(r.headers["Location"], "/offers")

    def test_login_is_rate_limited(self):
        self.client_for("consumer")
        c = self.app.test_client()
        for _ in range(5):
            self.post(c, "/login", email="consumer@example.test", password="wrong-password")
        r = self.post(c, "/login", email="consumer@example.test", password="password123")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many failed attempts", r.get_data(as_text=True))

    def test_security_headers_and_script_nonce(self):
        r = self.app.test_client().get("/")
        csp = r.headers["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        html = r.get_data(as_text=True)
        inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
        self.assertTrue(inline)
        for attrs in inline:   # every inline script carries this response's nonce
            self.assertIn(f'nonce="{nonce}"', attrs)
        self.assertIn("SameSite=Lax", r.headers.get("Set-Cookie", "SameSite=Lax"))

    def test_chat_cannot_reveal_hidden_posts(self):
        supplier = self.client_for("supplier")
        consumer = self.client_for("consumer")
        small = self.make_offer(supplier, title="Muffins", visible_consumers="1")
        hidden = self.make_offer(supplier, title="Secret pallet", size="large")   # distributors only
        r = consumer.get(f"/messages/with/1?ref=offer:{small}")
        cid = int(re.search(r"/messages/(\d+)", r.headers["Location"]).group(1))
        token = self.csrf(consumer)
        consumer.post(f"/api/messages/{cid}", json={"body": "hello", "ref": f"offer:{hidden}"},
                      headers={"X-CSRF-Token": token})
        data = consumer.get(f"/api/messages/{cid}?after=0").get_json()
        self.assertIsNone(data["messages"][0]["ref_type"])
        self.assertNotIn("Secret pallet", consumer.get(f"/messages/{cid}").get_data(as_text=True))

    def test_verification_documents_checked_and_downloaded(self):
        dist = self.client_for("distributor")
        for content, name in ((b"<html><script>alert(1)</script>", "cert.pdf"), (b"%PDF-1.4", "cert.html")):
            data = {"doc_type": "Food safety certificate", "document": (BytesIO(content), name), "_csrf": self.csrf(dist)}
            r = dist.post("/profile/documents", data=data, content_type="multipart/form-data", follow_redirects=True)
            self.assertIn("Upload a PDF, PNG or JPG file.", r.get_data(as_text=True))
        data = {"doc_type": "Food safety certificate", "document": (BytesIO(b"%PDF-1.4 ok"), "cert.pdf"),
                "_csrf": self.csrf(dist)}
        dist.post("/profile/documents", data=data, content_type="multipart/form-data")
        with dist.get("/documents/1") as r:
            self.assertEqual(r.status_code, 200)
            self.assertIn("attachment", r.headers["Content-Disposition"])

    def test_verified_badge_reset_when_org_changes(self):
        dist = self.client_for("distributor", org="Real Shelter")
        self.verify("distributor@example.test")
        self.post(dist, "/profile", name="Distributor", org_name="Totally Different Org")
        with self.app.app_context():
            from ecoserving.db import query
            row = query("SELECT verification_status FROM users WHERE email = 'distributor@example.test'", one=True)
        self.assertEqual(row["verification_status"], "unverified")

    def test_organizer_cannot_reaccept_withdrawn_volunteer(self):
        supplier = self.client_for("supplier")
        vol = self.client_for("volunteer")
        self.post(supplier, "/volunteer/new", title="Sort", tasks="Sort food", location="1 Main St",
                  start_time=future(2), end_time=future(4), slots="2")
        self.post(vol, "/volunteer/1/apply")
        self.post(vol, "/volunteer/1/withdraw")
        r = self.post(supplier, "/volunteer/signups/1/accept")
        self.assertIn("be changed any more", r.get_data(as_text=True))
        with self.app.app_context():
            from ecoserving.db import query
            self.assertEqual(query("SELECT status FROM volunteer_signups WHERE id = 1", one=True)["status"], "withdrawn")

    def test_seed_and_init_db_ask_first(self):
        r = self.app.test_cli_runner().invoke(args=["init-db"], input="n\n")
        self.assertNotEqual(r.exit_code, 0)
        self.assertIn("deletes ALL data", r.output)

    # -- reports ---------------------------------------------------------------
    def test_report_scam_and_admin_review(self):
        supplier = self.client_for("supplier", org="Shady Deli")
        consumer = self.client_for("consumer")
        oid = self.make_offer(supplier, title="Free pizza", visible_consumers="1")
        page = consumer.get(f"/offers/{oid}").get_data(as_text=True)
        self.assertIn(f"/report?target=offer:{oid}", page)
        self.assertNotIn("/report?target=", supplier.get(f"/offers/{oid}").get_data(as_text=True))  # not on own post
        self.assertEqual(supplier.get(f"/report?target=offer:{oid}").status_code, 404)
        r = self.post(consumer, "/report", target=f"offer:{oid}", category="scam", details="short")
        self.assertIn("10 to 2000 characters", r.get_data(as_text=True))
        r = self.post(consumer, "/report", target=f"offer:{oid}", category="scam",
                      details="They asked me for a $20 delivery fee by gift card.")
        self.assertIn("Your report was sent", r.get_data(as_text=True))
        r = self.post(consumer, "/report", target=f"offer:{oid}", category="scam", details="Again, same problem here.")
        self.assertIn("already reported", r.get_data(as_text=True))
        # Only admins can see reports.
        self.assertEqual(consumer.get("/admin/reports").status_code, 302)
        admin = self.admin_client()
        page = admin.get("/admin/reports").get_data(as_text=True)
        self.assertIn("$20 delivery fee by gift card", page)
        self.assertIn("Shady Deli", page)
        self.assertIn('<span class="badge-count" title="Open reports">1</span>', page)
        # Suspending the account logs them out, blocks login and takes down their open posts.
        self.post(admin, "/admin/users/1/suspend", reason="Scam")
        self.assertEqual(supplier.get("/dashboard").status_code, 302)
        r = self.post(self.app.test_client(), "/login", email="supplier@example.test", password="password123")
        self.assertIn("suspended", r.get_data(as_text=True))
        with self.app.app_context():
            from ecoserving.db import query
            self.assertEqual(query("SELECT status FROM food_offers WHERE id = ?", (oid,), one=True)["status"], "cancelled")
        self.post(admin, "/admin/reports/1", status="resolved", admin_note="Account suspended")
        self.assertIn("Account suspended", admin.get("/admin/reports?status=resolved").get_data(as_text=True))

    def test_report_user_from_chat_and_takedown(self):
        dist = self.client_for("distributor")
        self.verify("distributor@example.test")
        supplier = self.client_for("supplier")
        r = self.post(dist, "/food-requests/new", follow=False, title="Bread", description="Loaves",
                      quantity="5", location="1 Main St", needed_by=future(5))
        rid = int(r.headers["Location"].rsplit("/", 1)[1])
        self.post(supplier, "/report", target=f"food_request:{rid}", category="fraud",
                  details="This shelter does not exist at that address.")
        self.post(supplier, "/report", target="user:1", category="harassment", details="Rude and threatening messages.")
        self.assertEqual(supplier.get("/report?target=user:2").status_code, 404)   # yourself
        admin = self.admin_client()
        self.post(admin, "/admin/reports/1/takedown")
        with self.app.app_context():
            from ecoserving.db import query
            self.assertEqual(query("SELECT status FROM food_requests WHERE id = ?", (rid,), one=True)["status"], "closed")
            self.assertEqual(query("SELECT COUNT(*) AS n FROM reports", one=True)["n"], 2)

    # -- demo ------------------------------------------------------------------
    def demo_app(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        app = create_app({"TESTING": True, "DEMO_MODE": True, "RATELIMIT_ENABLED": False,
                          "DATABASE": os.path.join(tmp, "demo.sqlite"), "UPLOAD_FOLDER": os.path.join(tmp, "up")})
        with app.app_context():
            from ecoserving.seed import seed
            seed()
        return app

    def test_demo_is_off_in_the_normal_app(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/demo").status_code, 404)
        self.assertEqual(c.get("/demo/frame/supplier/_demo_login").status_code, 404)
        self.assertEqual(c.post("/demo/reset").status_code, 400)           # no CSRF token, and no such route
        self.assertEqual(c.get("/").headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", c.get("/").headers["Content-Security-Policy"])

    def test_demo_panes_have_separate_logins(self):
        c = self.demo_app().test_client()
        page = c.get("/demo")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("demo.js", page.get_data(as_text=True))
        seen = {}
        for role in ("supplier", "distributor", "volunteer", "consumer"):
            r = c.get(f"/demo/frame/{role}/_demo_login")
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.headers["Location"], f"/demo/frame/{role}/dashboard")
        # One cookie jar, four roles: each pane still sees its own dashboard.
        for role, heading in (("supplier", "Supplier dashboard"), ("distributor", "Distributor dashboard"),
                              ("volunteer", "Volunteer dashboard"), ("consumer", "Free food near you")):
            html = c.get(f"/demo/frame/{role}/dashboard").get_data(as_text=True)
            self.assertIn(heading, html, role)
            self.assertIn(f'href="/demo/frame/{role}/offers"' if role != "volunteer" else f'/demo/frame/{role}/volunteer', html)

    def test_demo_scam_finale_and_admin_pane(self):
        c = self.demo_app().test_client()
        token = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/demo").get_data(as_text=True)).group(1)
        self.assertNotIn("progress", c.get("/demo").get_data(as_text=True))                    # no progress bar
        self.assertIn('class="pane pane-admin"', c.get("/demo").get_data(as_text=True))
        c.get("/demo/frame/consumer/_demo_login")
        self.assertNotIn("pay $15", c.get("/demo/frame/consumer/offers").get_data(as_text=True))
        c.post("/demo/plant-scam", headers={"X-CSRF-Token": token})
        offers = c.get("/demo/frame/consumer/offers").get_data(as_text=True)
        self.assertIn("FREE food box: pay $15 delivery fee first", offers)
        # Admin pane logs straight into the reports page (and only a same-site `next` is followed).
        r = c.get("/demo/frame/admin/_demo_login?next=/admin/reports")
        self.assertEqual(r.headers["Location"], "/demo/frame/admin/admin/reports")
        r = c.get("/demo/frame/admin/_demo_login?next=//evil.example")
        self.assertEqual(r.headers["Location"], "/demo/frame/admin/dashboard")
        self.assertEqual(c.get("/demo/frame/admin/admin/reports").status_code, 200)

    def test_demo_command_line_options_become_url_options(self):
        from ecoserving.demo import build_url
        self.assertEqual(build_url(), "http://127.0.0.1:5001/demo")
        self.assertEqual(build_url(5002, beat=6.0, pace=1.0, speed=2.0, admin=3.0, autostart=True),
                         "http://127.0.0.1:5002/demo?beat=6&pace=1&speed=2&admin=3&autostart=1")
        self.assertEqual(build_url(beat=2.5), "http://127.0.0.1:5001/demo?beat=2.5")

    def test_demo_page_carries_the_command_line_timing(self):
        app = self.demo_app()
        plain = app.test_client().get("/demo").get_data(as_text=True)
        self.assertIn("data-options='{}'", plain)
        app.config["DEMO_OPTIONS"] = {"speed": 1.5, "beat": 2.0}
        page = app.test_client().get("/demo").get_data(as_text=True)
        self.assertIn('data-options=\'{"beat":2.0,"speed":1.5}\'', page.replace(", ", ",").replace(": ", ":"))

    def test_demo_refuses_a_port_that_is_taken(self):
        import socket
        from ecoserving.demo import main, port_in_use
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            self.assertTrue(port_in_use(port))
            with self.assertRaises(SystemExit) as ctx:
                main(["--port", str(port)])
            self.assertIn("already in use", str(ctx.exception))

    def test_demo_reset_restores_fresh_data(self):
        c = self.demo_app().test_client()
        token = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/demo").get_data(as_text=True)).group(1)
        c.get("/demo/frame/supplier/_demo_login")
        r = c.post("/demo/reset", headers={"X-CSRF-Token": token})
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertEqual(c.get("/demo/frame/supplier/_demo_login").status_code, 302)   # accounts exist again

    def test_seed(self):
        with self.app.app_context():
            from ecoserving.seed import seed
            seed()


if __name__ == "__main__":
    unittest.main()
