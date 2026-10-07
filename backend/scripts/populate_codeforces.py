"""Populate the catalog from the Codeforces API.

Thin CLI over the POST /api/sync/catalog logic, for local setup. Run:

    uv run python -m scripts.populate_codeforces
"""

from app import create_app
from routes.sync import sync_catalog

if __name__ == "__main__":
    with create_app().app_context():
        print(sync_catalog())
