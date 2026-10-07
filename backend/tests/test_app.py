"""The app factory's own surface: what sits outside the API blueprint."""


def test_healthz_needs_no_access_token(client):
    """The container healthcheck cannot present a Cloudflare Access token, so
    /healthz must stay outside the auth hook that guards every /api route."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
