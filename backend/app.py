"""Flask application: the one place SQLAlchemy and Alembic are wired up.

`model.db.db` and its metadata already exist; the extension is only *bound* to
Flask here, so `flask --app app db ...` and a WSGI server see the same objects.

Config comes from `config.load_config()` (the only reader of `os.environ`).
`.env` is loaded first, so local development needs no exported variables.
"""

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from sqlalchemy import select
from werkzeug.exceptions import HTTPException

load_dotenv(Path(__file__).with_name(".env"))
from config import load_config
from model import db
from routes import api_bp

migrate = Migrate(
    compare_type=True,
    compare_server_default=True,
    render_as_batch=False,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(load_config())
    db.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(api_bp, url_prefix="/api")

    if app.config["AUTH_DISABLED"]:
        # A deployment that meant to verify Cloudflare Access but silently runs
        # as one user is the failure mode worth shouting about: it is
        # indistinguishable from a working app until someone signs in. Warning
        # level, because that is what reaches a container's stderr by default.
        app.logger.warning(
            "AUTH_DISABLED is on: every request is %s, and no Access token is "
            "checked. Development only.", app.config["DEV_EMAIL"],
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Readiness for the container healthcheck.

        Deliberately outside `api_bp`: a healthcheck cannot present a Cloudflare
        Access token, so it must not run through the auth hook. It touches the
        database, so a backend that has lost Postgres reports unhealthy rather
        than merely alive.
        """
        db.session.execute(select(1))
        return {"status": "ok"}

    @app.errorhandler(HTTPException)
    def json_error(error: HTTPException) -> tuple[dict, int]:
        """Every refusal as JSON, carrying the route's own wording.

        Routes abort with a human sentence ("cf_handle already in use",
        "no accepted submission in this attempt's window"). Without this, Flask
        answers with an HTML page, and a client can only guess at the reason
        from the status code.
        """
        return {"message": error.description}, error.code or 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(port=5001)
