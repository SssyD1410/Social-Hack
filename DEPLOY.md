# Publishing EcoServing on PythonAnywhere

PythonAnywhere runs Flask apps and keeps files on disk, so the SQLite database and uploaded photos survive restarts.
The free plan gives you `https://<username>.pythonanywhere.com`; a paid plan adds a custom domain.

Replace `<username>` below with your PythonAnywhere username.

## 1. Get the code onto PythonAnywhere

Sign up at <https://www.pythonanywhere.com>, then open **Consoles → Bash** and run:

```bash
git clone https://github.com/SssyD1410/Social-Hack.git
cd Social-Hack
python3.12 -m venv ~/.virtualenvs/ecoserving
source ~/.virtualenvs/ecoserving/bin/activate
pip install -r requirements.txt
```

(Any Python 3.10 or newer works; use the same version in step 2.)

## 2. Create the web app

1. Open the **Web** tab → **Add a new web app** → **Next** → **Manual configuration** (not "Flask") → pick
   **Python 3.12** → **Next**.
2. Under **Virtualenv**, enter `/home/<username>/.virtualenvs/ecoserving`.
3. Under **Code**, click the **WSGI configuration file** link, delete everything in it, and paste:

   ```python
   import sys
   path = "/home/<username>/Social-Hack"
   if path not in sys.path:
       sys.path.insert(0, path)
   from wsgi import application
   ```

   Save.
4. Under **Static files**, add URL `/static/` with directory `/home/<username>/Social-Hack/foodrelay/static`
   (optional, makes photos load faster).
5. Under **Security**, turn on **Force HTTPS**.
6. Click the green **Reload** button and open `https://<username>.pythonanywhere.com`.

The first request creates the database and a random secret key in `Social-Hack/instance/` (both stay out of git).

## 3. Create your admin account

Admins verify distributors. Back in the Bash console:

```bash
cd ~/Social-Hack
source ~/.virtualenvs/ecoserving/bin/activate
flask --app foodrelay create-admin
```

It asks for an email and a password. Everyone else signs up through the site.

**Do not run `flask --app foodrelay seed` on the live site.** It wipes the database and creates demo accounts
whose password is published in this repository.

## Updating the site later

After pushing new commits to GitHub:

```bash
cd ~/Social-Hack && git pull
```

Then press **Reload** on the Web tab. Database changes are applied automatically on start.

## Notes

- Errors show up in the **Web** tab's error log.
- Back up `instance/` (the database, uploads and secret key) from the **Files** tab now and then.
- Maps, routes and address search use free public services (Esri tiles, the OSRM demo server, OpenStreetMap
  Nominatim) straight from the visitor's browser. They are fine for a small site; switch to your own or a paid
  provider if traffic grows.
