from datetime import datetime, timedelta, timezone

import pytest
from flask import g
from werkzeug.exceptions import Forbidden

import routes
from conftest import auth
from model import Attempt, OverallRating, Problem, Tag, TagGroup, TopicRating, User, db
from routes.report import group_ratings

URL = "/api/users/me"

BAD_TOKENS = [{}, auth("bad")]


@pytest.mark.parametrize("headers", BAD_TOKENS)
def test_me_refuses_missing_or_bad_token(client, headers):
    assert client.get(URL, headers=headers).status_code == 403


def test_unknown_verified_email_becomes_a_user(client):
    """No invite list: a verified Cloudflare email is the identity."""
    r = client.get(URL, headers=auth("newcomer@example.com"))
    assert r.status_code == 200
    assert r.json["email"] == "newcomer@example.com"
    assert r.json["cf_handle"] is None  # set later through PUT /me
    assert r.json["seeded"] is False
    assert r.json["rating"] == {"rating": 800, "rd": 350}
    assert db.session.query(User).filter_by(email="newcomer@example.com").one()


def test_me_unseeded_returns_new_user_prior(client, user):
    r = client.get(URL, headers=auth(user.email))
    assert r.status_code == 200
    body = r.json
    assert (body["id"], body["email"], body["cf_handle"]) == (user.id, user.email, user.cf_handle)
    assert body["seeded"] is False
    assert body["rating"] == {"rating": 800, "rd": 350}
    assert body["groups"] and all(g["rating"] == 800 for g in body["groups"])
    assert body["history"] == []


def test_me_seeded_returns_rating_groups_and_past_year(client, user):
    now = datetime.now(timezone.utc)
    tag, group = db.session.execute(
        db.select(Tag, TagGroup).join(TagGroup, Tag.group_id == TagGroup.id)
    ).first()
    db.session.add(OverallRating(user_id=user.id, rating=1500, rd=100, last_practised_at=now))
    db.session.add(TopicRating(user_id=user.id, tag_id=tag.id, rating_offset=200, rd=55,
                               last_practised_at=now))

    def attempt(problem, days_ago, rated, after):
        at = now - timedelta(days=days_ago)
        return Attempt(user_id=user.id, problem_id=problem.id, source="self_selected",
                       started_at=at - timedelta(minutes=45), scored_at=at, s=0,
                       e_model=0.5, rated=rated, overall_after=after)

    p1, p2, p3 = Problem.query.limit(3).all()
    db.session.add_all([
        attempt(p1, 400, True, 1450),  # older than a year: dropped
        attempt(p2, 2, True, 1500),    # kept
        attempt(p3, 1, False, None),   # unrated: dropped
    ])
    db.session.flush()

    body = client.get(URL, headers=auth(user.email)).json

    assert body["rating"]["rating"] == 1500
    assert body["seeded"] is True
    assert 100 <= body["rating"]["rd"] < 101  # aged by milliseconds, not to the cap
    assert [h["rating"] for h in body["history"]] == [1500]

    groups = {g["name"]: g["rating"] for g in body["groups"]}
    assert list(groups) == sorted(groups)
    assert len(groups) == db.session.scalar(db.select(db.func.count(db.distinct(Tag.group_id))))
    assert groups[group.name] > 1500
    assert all(r == 1500 for name, r in groups.items() if name != group.name)


def test_me_is_seeded_even_with_no_rated_attempt(client, user):
    """Seededness is the `overall_rating` row, not a guess from the payload: a
    seed that replayed no contest leaves the rating on its prior and the history
    empty, which is exactly what an unseeded account looks like."""
    db.session.add(OverallRating(user_id=user.id, rating=800, rd=350,
                                 last_practised_at=datetime.now(timezone.utc)))
    db.session.flush()

    body = client.get(URL, headers=auth(user.email)).json
    assert body["seeded"] is True
    assert body["history"] == []


def test_access_claims_are_bound_to_the_request(app, monkeypatch):
    monkeypatch.setattr(
        routes, "verify_access_jwt",
        lambda token: {"email": "claims@example.com", "sub": "abc"},
    )
    with app.test_request_context(headers=auth("claims@example.com")):
        routes.require_access()
        assert g.claims["sub"] == "abc"
        assert g.user.email == "claims@example.com"


def test_access_token_without_email_claim_is_refused(app, monkeypatch):
    monkeypatch.setattr(routes, "verify_access_jwt", lambda token: {"sub": "abc"})
    with app.test_request_context(headers=auth("whatever")):
        with pytest.raises(Forbidden):
            routes.require_access()


def test_put_me_saves_handle(client, user):
    r = client.put(URL, headers=auth(user.email), json={"cf_handle": "  new_handle  "})
    assert r.status_code == 200
    assert r.json == {"cf_handle": "new_handle"}
    assert db.session.get(User, user.id).cf_handle == "new_handle"


def test_put_me_is_idempotent_for_the_same_handle(client, user):
    reply = client.put(URL, headers=auth(user.email), json={"cf_handle": user.cf_handle})
    assert reply.status_code == 200
    assert reply.json == {"cf_handle": user.cf_handle}


@pytest.mark.parametrize("body", [{}, {"cf_handle": ""}, {"cf_handle": "   "},
                                   {"cf_handle": 5}, {"nope": "x"}])
def test_put_me_rejects_blank_or_missing_handle(client, user, body):
    assert client.put(URL, headers=auth(user.email), json=body).status_code == 400


def test_put_me_rejects_handle_already_taken(client, user):
    db.session.add(User(email="other@example.com", cf_handle="taken"))
    db.session.flush()
    r = client.put(URL, headers=auth(user.email), json={"cf_handle": "taken"})
    assert r.status_code == 409


def test_put_me_locks_the_handle_after_seeding(client, user):
    """Re-pointing a seeded account at another CF handle would mix two histories."""
    db.session.add(OverallRating(user_id=user.id, rating=1400, rd=200,
                                 last_practised_at=datetime.now(timezone.utc)))
    db.session.flush()

    r = client.put(URL, headers=auth(user.email), json={"cf_handle": "someone_else"})
    assert r.status_code == 409
    assert db.session.get(User, user.id).cf_handle == user.cf_handle


@pytest.mark.parametrize("headers", BAD_TOKENS)
def test_put_me_refuses_missing_or_bad_token(client, headers):
    r = client.put(URL, headers=headers, json={"cf_handle": "x"})
    assert r.status_code == 403


def test_group_ratings_weights_precise_tags_more():
    out = group_ratings(1500, [("graphs", 100, 50), ("graphs", -100, 150), ("dp", 0, 150)])
    assert [g["name"] for g in out] == ["dp", "graphs"]
    assert out[0]["rating"] == 1500
    assert out[1]["rating"] == pytest.approx(1500 + 100 * (9 - 1) / (9 + 1))
