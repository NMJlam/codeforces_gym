"""config.load_config is the only reader of os.environ, so these are the
startup guards: a contradictory environment must fail while building the app,
not on the first request that happens to need the variable.
"""

import pytest

from config import ConfigError, load_config

VARS = ("DATABASE_URL", "SECRET_KEY", "CF_TEAM_DOMAIN", "CF_AUD",
        "AUTH_DISABLED", "DEV_EMAIL", "ENV")
CLOUDFLARE = {
    "DATABASE_URL": "postgresql+psycopg://user@host/db",
    "SECRET_KEY": "s",
    "CF_TEAM_DOMAIN": "https://team.cloudflareaccess.com",
    "CF_AUD": "aud",
}


@pytest.fixture
def env(monkeypatch):
    def apply(**values: str) -> None:
        for name in VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in values.items():
            monkeypatch.setenv(name, value)
    return apply


def test_reads_the_prd_variables(env):
    env(**CLOUDFLARE)
    config = load_config()
    assert config["SQLALCHEMY_DATABASE_URI"] == CLOUDFLARE["DATABASE_URL"]
    assert config["SECRET_KEY"] == "s"
    assert config["CF_TEAM_DOMAIN"] == CLOUDFLARE["CF_TEAM_DOMAIN"]
    assert config["CF_AUD"] == "aud"
    assert config["AUTH_DISABLED"] is False
    assert config["ENV"] == "production"  # unset ENV means production


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_auth_disabled_accepts_truthy_spellings(env, value):
    env(**CLOUDFLARE, ENV="development", AUTH_DISABLED=value,
        DEV_EMAIL="dev@example.com")
    assert load_config()["AUTH_DISABLED"] is True


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_auth_disabled_is_off_for_everything_else(env, value):
    env(**CLOUDFLARE, AUTH_DISABLED=value)
    assert load_config()["AUTH_DISABLED"] is False


def test_auth_disabled_outside_development_refuses_to_start(env):
    env(**CLOUDFLARE, AUTH_DISABLED="1", ENV="production",
        DEV_EMAIL="dev@example.com")
    with pytest.raises(ConfigError, match="development"):
        load_config()


def test_auth_disabled_without_dev_email_refuses_to_start(env):
    env(**CLOUDFLARE, AUTH_DISABLED="1", ENV="development")
    with pytest.raises(ConfigError, match="DEV_EMAIL"):
        load_config()


def test_cloudflare_auth_needs_team_domain_and_audience(env):
    env(DATABASE_URL="postgresql+psycopg://user@host/db", SECRET_KEY="s")
    with pytest.raises(ConfigError, match="CF_TEAM_DOMAIN"):
        load_config()

    env(DATABASE_URL="postgresql+psycopg://user@host/db", SECRET_KEY="s",
        CF_TEAM_DOMAIN="https://team.cloudflareaccess.com")
    with pytest.raises(ConfigError, match="CF_AUD"):
        load_config()


def test_missing_database_and_secret_key_refuse_to_start(env):
    env()
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        load_config()

    env(SECRET_KEY="s")
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_config()
