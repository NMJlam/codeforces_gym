"""GET /skills and GET /history: the read-only views over the attempt log.
"""

from datetime import datetime, timedelta, timezone

import pytest

from conftest import auth
from model import (Attempt, OverallRating, PracticeSession, Problem, Tag, TopicRating,
                   User, db)

SKILLS = "/api/skills"
HISTORY = "/api/history"


@pytest.fixture
def history(app, user):
    """Three of the user's attempts (one per source) and one that is not theirs."""
    now = datetime.now(timezone.utc)
    tag = db.session.query(Tag).filter_by(name="dp").one()
    db.session.add(OverallRating(user_id=user.id, rating=1500.0, rd=100.0,
                                 last_practised_at=now))
    session = PracticeSession(user_id=user.id, tag_id=tag.id, started_at=now - timedelta(days=1))
    db.session.add(session)
    db.session.flush()

    other = User(email="other@example.com", cf_handle="other_handle")
    db.session.add(other)
    db.session.flush()

    problems = Problem.query.filter(Problem.rating.isnot(None)).limit(4).all()

    def attempt(owner, problem, source, minutes_ago, s, **extra):
        started = now - timedelta(minutes=minutes_ago)
        return Attempt(
            user_id=owner.id, problem_id=problem.id, source=source,
            session_id=session.id if source == "session" else None,
            slot="warmup" if source == "session" else None,
            started_at=started, scored_at=started, s=s, rated=True, e_model=0.5,
            # A solve inside the 45-minute window (the schema enforces it).
            accepted_at=started + timedelta(minutes=5) if s == 1 else None,
            overall_after=1500.0, **extra,
        )

    db.session.add_all([
        attempt(user, problems[0], "session", 30, 0, key_idea="parity"),
        attempt(user, problems[1], "self_selected", 60, 1),
        attempt(user, problems[2], "contest", 90, 0, upsolved_at=now),
        attempt(other, problems[3], "self_selected", 10, 1),
    ])
    db.session.flush()
    return session, problems


def test_history_returns_only_this_users_attempts_newest_first(client, user, history):
    session, problems = history

    body = client.get(HISTORY, headers=auth(user.email)).json

    assert [attempt["source"] for attempt in body["attempts"]] == [
        "session", "self_selected", "contest",
    ]
    started = [entry["started_at"] for entry in body["attempts"]]
    assert started == sorted(started, reverse=True)  # newest first
    assert {attempt["problem"]["contest_id"] for attempt in body["attempts"]} == {
        problem.contest_id for problem in problems[:3]
    }

    solved = body["attempts"][1]
    assert solved["s"] == 1 and solved["e_model"] == pytest.approx(0.5)
    assert solved["overall_after"] == 1500.0
    assert solved["problem"]["editorial_search"].endswith("editorial")
    assert body["attempts"][2]["upsolved_at"] is not None


def test_history_counts_the_whole_log_for_the_header(client, user, history):
    body = client.get(HISTORY, headers=auth(user.email)).json

    assert body["attempts_total"] == 3  # the other user's attempt is not counted
    assert body["rated_total"] == 3
    assert body["solved_total"] == 1


def test_history_pages_the_log(client, user, history):
    first = client.get(f"{HISTORY}?page=1&per_page=2", headers=auth(user.email)).json
    second = client.get(f"{HISTORY}?page=2&per_page=2", headers=auth(user.email)).json
    past_the_end = client.get(f"{HISTORY}?page=3&per_page=2", headers=auth(user.email)).json

    assert (first["page"], first["per_page"]) == (1, 2)
    assert [attempt["source"] for attempt in first["attempts"]] == ["session", "self_selected"]
    assert [attempt["source"] for attempt in second["attempts"]] == ["contest"]
    assert past_the_end["attempts"] == []
    # The counters describe the log, not the page.
    assert all(page["attempts_total"] == 3 for page in (first, second, past_the_end))


def test_history_searches_problem_names_handles_and_notes(client, user, history):
    target = history[1][0]
    handle = f"{target.contest_id}{target.problem_index}"

    by_name = client.get(HISTORY, query_string={"q": target.name}, headers=auth(user.email)).json
    assert [attempt["problem"]["name"] for attempt in by_name["attempts"]] == [target.name]
    assert by_name["q"] == target.name  # echoed back for the client's range label

    by_handle = client.get(HISTORY, query_string={"q": handle}, headers=auth(user.email)).json
    assert [attempt["problem"]["name"] for attempt in by_handle["attempts"]] == [target.name]

    by_note = client.get(HISTORY, query_string={"q": "parity"}, headers=auth(user.email)).json
    assert [attempt["source"] for attempt in by_note["attempts"]] == ["session"]

    missing = client.get(HISTORY, query_string={"q": "no such problem"}, headers=auth(user.email)).json
    assert missing["attempts"] == [] and missing["attempts_total"] == 0



def test_history_never_exposes_tags(client, user, history):
    payload = client.get(HISTORY, headers=auth(user.email)).json
    assert "tags" not in str(payload)


def test_skills_labels_each_tag_and_groups_the_ratings(client, user, app):
    now = datetime.now(timezone.utc)
    weak = db.session.query(Tag).filter_by(name="dp").one()
    strong = db.session.query(Tag).filter_by(name="graphs").one()
    unknown = db.session.query(Tag).filter_by(name="trees").one()
    above = db.session.query(Tag).filter_by(name="matrices").one()

    db.session.add(OverallRating(user_id=user.id, rating=1500.0, rd=100.0,
                                 last_practised_at=now))
    db.session.add_all([
        TopicRating(user_id=user.id, tag_id=weak.id, rating_offset=-200.0, rd=55.0,
                    last_practised_at=now),
        TopicRating(user_id=user.id, tag_id=strong.id, rating_offset=50.0, rd=55.0,
                    last_practised_at=now),
    ])
    db.session.flush()

    body = client.get(SKILLS, headers=auth(user.email)).json

    states = {entry["tag"]: entry for entry in body["tags"]}
    assert states["dp"]["state"] == "weak"
    assert states["dp"]["rating"] == pytest.approx(1300.0)
    assert states["graphs"]["state"] == "strong"
    assert states["graphs"]["rating"] == pytest.approx(1550.0)
    assert states[unknown.name]["state"] == "unknown"  # never practised, rd at the cap
    assert states[above.name]["state"] == "not_yet_relevant"  # emerges above 1500
    assert above.emergence_rating > 1500

    assert body["overall"] == {"rating": 1500.0}
    groups = {group["name"]: group["rating"] for group in body["groups"]}
    assert len(groups) == db.session.scalar(db.select(db.func.count(db.distinct(Tag.group_id))))
    assert groups["DP & counting"] < 1500  # pulled down by the weak dp offset
    assert groups["Graphs"] > 1500


def test_skills_without_a_seeded_rating_still_labels_the_tags(client, user):
    body = client.get(SKILLS, headers=auth(user.email)).json
    assert body["overall"] == {"rating": 800.0}
    assert body["tags"] and all(entry["state"] for entry in body["tags"])
