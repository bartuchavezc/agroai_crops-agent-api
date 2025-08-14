"""
WSGI entry point for the application.
This file is used for production deployment with Gunicorn or similar WSGI servers.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run() 