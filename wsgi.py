"""WSGI entry point for production hosts (PythonAnywhere, gunicorn, ...). See DEPLOY.md."""

from foodrelay import create_app

application = app = create_app()
