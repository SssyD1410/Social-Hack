"""WSGI entry point for production hosts (PythonAnywhere, gunicorn, ...)."""

import os

from werkzeug.middleware.proxy_fix import ProxyFix

# Production is served over HTTPS only: send the session cookie with the Secure flag.
os.environ.setdefault("ECOSERVING_HTTPS", "1")

from ecoserving import create_app  # noqa: E402

app = create_app()
# The host's proxy terminates HTTPS; trust its one X-Forwarded-For / -Proto hop so the app sees the real
# client address (for rate limits) and knows the request was HTTPS (for HSTS).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
application = app
