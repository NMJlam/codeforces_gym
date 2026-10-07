"""The client's job is the envelope, the timeout and the single retry; these
check those, with urlopen mocked so no test touches the network.
"""

import json
from datetime import datetime, timezone
from urllib.error import URLError

import pytest

import codeforces
from codeforces import (
    CodeforcesError,
    call,
    is_accepted,
    is_contestant,
    submission_key,
    submitted_at,
    user_status,
)


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def ok(result, url_sink=None):
    def opener(url, timeout):
        if url_sink is not None:
            url_sink.append((url, timeout))
        return FakeResponse({"status": "OK", "result": result})
    return opener


def test_call_returns_the_result_and_sends_encoded_params(monkeypatch):
    seen = []
    monkeypatch.setattr(codeforces, "urlopen", ok([{"handle": "tourist"}], seen))

    assert call("user.info", {"handles": "tourist"}) == [{"handle": "tourist"}]
    url, timeout = seen[0]
    assert url == "https://codeforces.com/api/user.info?handles=tourist"
    assert timeout == codeforces.TIMEOUT


def test_call_without_params_has_no_query_string(monkeypatch):
    seen = []
    monkeypatch.setattr(codeforces, "urlopen", ok([], seen))
    call("contest.list")
    assert seen[0][0] == "https://codeforces.com/api/contest.list"


def test_failed_envelope_becomes_one_exception(monkeypatch):
    monkeypatch.setattr(codeforces, "urlopen", lambda url, timeout: FakeResponse(
        {"status": "FAILED", "comment": "handle: nobody not found"}))

    with pytest.raises(CodeforcesError, match="not found"):
        call("user.info", {"handles": "nobody"})


def test_non_envelope_payload_is_rejected(monkeypatch):
    monkeypatch.setattr(codeforces, "urlopen",
                        lambda url, timeout: FakeResponse([1, 2, 3]))
    with pytest.raises(CodeforcesError, match="unexpected payload"):
        call("contest.list")


def test_transport_error_becomes_one_exception(monkeypatch):
    def explode(url, timeout):
        raise URLError("connection refused")
    monkeypatch.setattr(codeforces, "urlopen", explode)

    with pytest.raises(CodeforcesError, match="connection refused"):
        call("contest.list")


def test_retry_once_retries_exactly_once(monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    attempts = []

    def flaky(url, timeout):
        attempts.append(url)
        if len(attempts) == 1:
            raise URLError("connection reset")
        return FakeResponse({"status": "OK", "result": [{"id": 7}]})

    monkeypatch.setattr(codeforces, "urlopen", flaky)
    assert call("user.status", {"handle": "h"}, retry_once=True) == [{"id": 7}]
    assert len(attempts) == 2


def test_without_retry_once_a_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    attempts = []

    def explode(url, timeout):
        attempts.append(url)
        raise URLError("connection reset")

    monkeypatch.setattr(codeforces, "urlopen", explode)
    with pytest.raises(CodeforcesError):
        call("characteristic", {"handle": "h"})
    assert len(attempts) == 1

    attempts.clear()
    with pytest.raises(CodeforcesError):
        call("user.status", {"handle": "h"}, retry_once=True)
    assert len(attempts) == 2  # one retry, no more


def test_user_status_pages_until_a_short_page(monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    full_page = [{"id": i} for i in range(codeforces.STATUS_PAGE)]
    pages = [full_page, [{"id": -1}]]
    starts = []

    def opener(url, timeout):
        starts.append(url)
        return FakeResponse({"status": "OK", "result": pages[len(starts) - 1]})

    monkeypatch.setattr(codeforces, "urlopen", opener)
    submissions = user_status("h")

    assert len(submissions) == codeforces.STATUS_PAGE + 1
    assert "from=1" in starts[0]
    assert f"from={codeforces.STATUS_PAGE + 1}" in starts[1]
    assert len(starts) == 2


def test_submission_shape_helpers_decode_codeforces_json():
    submission = {
        "id": 1234,
        "contestId": 1900,
        "creationTimeSeconds": 1_600_000_000,
        "verdict": "OK",
        "problem": {"contestId": 1900, "index": "C", "name": "X"},
        "author": {"participantType": "CONTESTANT"},
    }
    assert submission_key(submission) == (1900, "C")
    assert is_accepted(submission)
    assert is_contestant(submission)
    assert submitted_at(submission) == datetime.fromtimestamp(
        1_600_000_000, tz=timezone.utc)

    practice = {**submission, "verdict": "WRONG_ANSWER",
                "author": {"participantType": "PRACTICE"}}
    assert not is_accepted(practice)
    assert not is_contestant(practice)
    assert submission_key({"id": 1}) is None  # no contest/index at all
    assert submitted_at({"id": 1}) is None
