# FoodRelay

FoodRelay helps surplus food reach people who need it. Shops and restaurants post food they'd otherwise throw
away; verified organizations, individual volunteers and consumers claim it; everyone coordinates in built-in chat.

## Roles

| Role | Who | Can do |
|------|-----|--------|
| **Supplier** | Shops, bakeries, restaurants with surplus | Post food offers (description, type, size, dietary notes, location, pickup deadline) and choose who sees each one: distributors, volunteers and/or consumers. Request volunteers. Pledge to fill distributors' food requests. |
| **Distributor** | Shelters, food banks, pantries | Upload certification and get verified by an admin. Once verified: claim offers (and take responsibility for pickup and delivery), post food requests (description, quantity, location, time), request volunteers. |
| **Volunteer** | Individuals, not acting for an organization | Sign up for volunteer requests, claim offers opened to volunteers. |
| **Consumer** | Anyone who wants food | View and reserve **small** offers that suppliers have made visible to consumers. |
| **Admin** | FoodRelay staff | Review distributor documents and verify or reject them. |

Anyone can message the person behind an offer or request they can see. Each role has a public "Learn more" page at
`/learn/<role>`.

## Tech stack

- **Backend:** Python 3.10+ / Flask, server-rendered Jinja templates
- **Database:** SQLite (`instance/foodrelay.sqlite`); schema in [`foodrelay/schema.sql`](foodrelay/schema.sql)
- **Auth:** session cookies, Werkzeug password hashing (scrypt/pbkdf2), CSRF tokens on every POST
- **Chat:** JSON API polled every 3 seconds from the conversation page
- **Uploads:** distributor certification files stored in `instance/uploads/`, visible only to the owner and admins

```
foodrelay/
  __init__.py     app factory, CSRF
  db.py           SQLite helpers + `init-db` / `seed` CLI commands
  schema.sql      tables: users, verification_documents, food_offers, food_requests,
                  volunteer_requests, volunteer_signups, conversations, messages
  auth.py         register / login / logout
  main.py         landing, learn-more pages, dashboards, profile & verification uploads
  posts.py        food offers, food requests, volunteer requests
  chat.py         conversations and messages
  admin.py        distributor verification
  visibility.py   who can see / claim which offers
  templates/      Jinja templates (one dashboard per role, learn/<role>.html, ...)
  static/style.css
tests/test_app.py end-to-end tests with Flask's test client
```

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
flask --app foodrelay seed      # optional: reset DB and load demo data
flask --app foodrelay run --debug
```

Then open http://127.0.0.1:5000.

### Demo accounts (after `seed`)

All demo accounts use the password `foodrelay-demo`.

| Email | Role |
|-------|------|
| `admin@foodrelay.test` | Admin |
| `bakery@foodrelay.test` | Supplier (Sunrise Bakery) |
| `bistro@foodrelay.test` | Supplier (Green Fork Bistro) |
| `shelter@foodrelay.test` | Distributor, verified (Harbor Street Shelter) |
| `pantry@foodrelay.test` | Distributor, pending verification |
| `volunteer@foodrelay.test` | Volunteer |
| `consumer@foodrelay.test` | Consumer |

### Tests

```bash
python -m unittest discover tests
```

### Production notes

Set `FOODRELAY_SECRET_KEY` to a long random value, run behind a real WSGI server (e.g. `waitress` or `gunicorn`),
and serve over HTTPS. Create an admin by registering normally and running
`UPDATE users SET role = 'admin' WHERE email = '...'` against the database.
