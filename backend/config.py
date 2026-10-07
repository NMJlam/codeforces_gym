"""Every environment variable the app reads, in one place.

`create_app()` calls `load_config()` once and hands the result to Flask's
`app.config`; routes and the auth hook read `current_app.config`. That keeps
exactly one reader of `os.environ`, so what a deployment must set (and what it
must not set) is visible in one file instead of scattered `os.environ[...]`
lookups.

`.env` is loaded by `app.py` *before* this module runs, so `load_dotenv` values
are picked up here while real environment variables still win.
"""

import os

# Anything else (including "0"/"false"/unset) is disabled. AUTH_DISABLED only
# has a meaning in development, so a truthy value anywhere else is a mistake
# that would silently drop Cloudflare verification in production.
_TRUE = frozenset({"1", "true", "yes", "on"})
_DEVELOPMENT = "development"


class ConfigError(RuntimeError):
    """Missing or contradictory environment: raised while building the app."""


def _as_bool(raw: str) -> bool:
    return raw.strip().lower() in _TRUE


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def load_config() -> dict:
    """Read the seven PRD variables into Flask config keys.

    Refuses to start when the environment contradicts itself: dev auth outside
    development, dev auth without a DEV_EMAIL, or Cloudflare auth without the
    team domain / audience it verifies against.
    """
    env = os.environ.get("ENV", "").strip() or "production"
    auth_disabled = _as_bool(os.environ.get("AUTH_DISABLED", ""))
    secret_key = _required("SECRET_KEY")
    database_url = _required("DATABASE_URL")

    if auth_disabled and env != _DEVELOPMENT:
        raise ConfigError("AUTH_DISABLED is only allowed when ENV=development")

    dev_email = os.environ.get("DEV_EMAIL", "").strip()
    if auth_disabled and not dev_email:
        raise ConfigError("DEV_EMAIL is required when AUTH_DISABLED is on")

    if auth_disabled:
        team_domain = os.environ.get("CF_TEAM_DOMAIN", "").strip()
        audience = os.environ.get("CF_AUD", "").strip()
    else:
        team_domain = _required("CF_TEAM_DOMAIN")
        audience = _required("CF_AUD")

    return {
        "SECRET_KEY": secret_key,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "CF_TEAM_DOMAIN": team_domain,
        "CF_AUD": audience,
        "AUTH_DISABLED": auth_disabled,
        "DEV_EMAIL": dev_email,
        "ENV": env,
    }
