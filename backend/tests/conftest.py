"""Route tests run against the dev Postgres (the schema needs Postgres) inside
one app context whose session is rolled back after each test, so nothing is
left behind. Needs the catalog (problems, tags) synced.
"""

import os

os.environ["AUTH_DISABLED"] = "0"  # exercise the real auth path; set before .env loads

import jwt
import pytest

import routes
from app import create_app
from model import User, db


def fake_verify(token: str) -> dict:
    """Stands in for Cloudflare: the token *is* the email, "bad" fails."""
    if token == "bad":
        raise jwt.PyJWTError("bad signature")
    return {"email": token}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(routes, "verify_access_jwt", fake_verify)
    app = create_app()
    # One app context for the whole test, so requests reuse it and see the
    # test's unflushed rows. Binding the session to a connection we roll back
    # keeps every committing route (PUT /me, seed, session/attempt scoring,
    # syncs) from leaving anything in the dev database.
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()
        db.session.remove()
        # Flask-SQLAlchemy resolves the engine per app context, so configure(bind=)
        # has no effect; patch the session instance instead. create_savepoint makes
        # every route transaction (commit *or* rollback) a savepoint release, so the
        # outer transaction rolls it all back, leaving the dev database untouched.
        session = db.session()
        session.get_bind = lambda *a, **k: connection
        session.join_transaction_mode = "create_savepoint"
        try:
            yield app
        finally:
            db.session.remove()
            transaction.rollback()
            connection.close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user(app):
    u = User(email="route-test@example.com", cf_handle="route_test_handle")
    db.session.add(u)
    db.session.flush()
    return u


def auth(email: str) -> dict:
    return {"Cf-Access-Jwt-Assertion": email}
