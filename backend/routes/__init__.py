"""API blueprint, auth hook, and request identity.

One `before_request` resolves the request's user: during development from
`DEV_EMAIL`, otherwise from a verified Cloudflare Access JWT. Every route then
reads `g.user` / `g.claims` and never re-queries the user.

All configuration is read from `current_app.config`; `os.environ` has exactly
one reader (`config.load_config`).
"""

import jwt
from flask import Blueprint, abort, current_app, g, request
from sqlalchemy.exc import IntegrityError

from model import User, db

api_bp = Blueprint("api", __name__)

# Keyed by certs URL so the cache follows a changed CF_TEAM_DOMAIN (tests and
# reloads rebuild the app; the module global would otherwise go stale).
_jwks_client: jwt.PyJWKClient | None = None
_jwks_url: str | None = None


def get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client, _jwks_url
    certs_url = f"{current_app.config['CF_TEAM_DOMAIN']}/cdn-cgi/access/certs"
    if _jwks_client is None or _jwks_url != certs_url:
        _jwks_client = jwt.PyJWKClient(certs_url)
        _jwks_url = certs_url
    return _jwks_client


def verify_access_jwt(token: str) -> dict:
    signing_key = get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=current_app.config["CF_AUD"],
        issuer=current_app.config["CF_TEAM_DOMAIN"],
    )


def get_or_create_user(email: str) -> User:
    """The identity seam: a verified email either exists or becomes a user.

    New users start with no Codeforces handle (`PUT /api/users/me` sets it), so
    sign-up needs no extra endpoint or profile step.

    Two first requests for the same email can race — the dashboard loads
    `/users/me` and `/sessions/current` at the same time, and gunicorn runs more
    than one worker — so the insert can lose to the unique index. The loser
    re-reads the winner's row rather than failing a request on a brand-new
    deployment.
    """
    user = User.query.filter_by(email=email).one_or_none()
    if user is None:
        user = User(email=email)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            user = User.query.filter_by(email=email).one()
    return user


@api_bp.before_request
def require_access() -> None:
    """Resolve `g.user` for every /api request (see module docstring)."""
    if current_app.config["AUTH_DISABLED"]:
        g.claims = {"email": current_app.config["DEV_EMAIL"]}
        g.user = get_or_create_user(current_app.config["DEV_EMAIL"])
        return

    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if not token:
        abort(403, "a Cloudflare Access token is required")
    try:
        claims = verify_access_jwt(token)
    except (jwt.PyJWKClientError, jwt.PyJWTError):
        abort(403, "that Cloudflare Access token is not valid")

    email = claims.get("email")
    if not email:
        abort(403, "the access token carries no email claim")
    g.claims = claims
    g.user = get_or_create_user(email)
