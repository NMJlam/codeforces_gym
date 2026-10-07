"""The one Codeforces API client.

`urllib` only, no new dependency, and one `call` for every endpoint: the
envelope check, the 30 s timeout, the URL encoding and (where the PRD asks for
it) the single retry live here instead of in each route.

Callers own the ~1 call / 2 s pacing of sync jobs (`pace()` does the sleeping);
nothing here ever runs in the background.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

API_BASE = "https://codeforces.com/api"
TIMEOUT = 30
# PRD: respect ~1 call / 2 s in sync jobs. Used both between successive calls
# and before the one retry, so there is a single pacing constant.
PACING = 2.0
# user.status pages at most 10000 rows per request; a normal user needs one.
STATUS_PAGE = 10000


def pace() -> None:
    """Sleep the ~1 call / 2 s the PRD asks for between Codeforces calls."""
    time.sleep(PACING)


class CodeforcesError(RuntimeError):
    """Any failed Codeforces call, with a message safe to put in an HTTP body.

    Transport errors, non-JSON bodies and the API's own `status: FAILED`
    envelopes all arrive as this, so a route only has to catch one thing.
    """


def _request(url: str) -> Any:
    """One HTTP call, one envelope check. Raises CodeforcesError on failure."""
    try:
        with urlopen(url, timeout=TIMEOUT) as response:
            payload = json.load(response)
    except HTTPError as exc:
        # Codeforces reports API errors (bad handle, rate limit) as an HTTP
        # error with a JSON body; prefer its comment over "HTTP 400".
        raise CodeforcesError(_http_error_comment(exc)) from exc
    except (OSError, ValueError) as exc:
        raise CodeforcesError(f"Codeforces request failed: {exc}") from exc

    if not isinstance(payload, dict) or "status" not in payload:
        raise CodeforcesError("Codeforces returned an unexpected payload")
    if payload["status"] != "OK":
        raise CodeforcesError(f"Codeforces error: {payload.get('comment', 'unknown')}")
    return payload.get("result")


def _http_error_comment(exc: HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8", "replace"))
        comment = body.get("comment")
    except (ValueError, OSError):
        comment = None
    return f"Codeforces error: {comment or f'HTTP {exc.code}'}"


def call(method: str, params: Mapping[str, str | int] | None = None, *,
         retry_once: bool = False) -> Any:
    """Call one Codeforces API method and return its `result`.

    `retry_once=True` makes exactly one retry, after the pacing interval — the
    PRD's "Done = one CF API call (one retry)".
    """
    url = f"{API_BASE}/{method}"
    if params:
        url = f"{url}?{urlencode(params)}"

    failure: CodeforcesError | None = None
    for attempt in range(2 if retry_once else 1):
        if attempt:
            pace()
        try:
            return _request(url)
        except CodeforcesError as exc:
            failure = exc
    raise failure  # type: ignore[misc]  # only reachable after a failure


def user_info(handle: str) -> dict:
    """The handle's current Codeforces profile (rating, rank, ...)."""
    result = call("user.info", {"handles": handle})
    if not result:
        raise CodeforcesError(f"Codeforces error: no such handle {handle}")
    return result[0]


def user_rating(handle: str) -> list[dict]:
    """The handle's rated-contest history, oldest first (as Codeforces sends it)."""
    return call("user.rating", {"handle": handle})


def recent_submissions(handle: str, *, retry_once: bool = True) -> list[dict]:
    """The newest page of the handle's submissions.

    This is the Done check's single call (PRD: "Done = one CF API call (one
    retry)"). One page is always enough: an accepted submission for an attempt
    that started minutes ago is at the very top of the list.
    """
    return call("user.status", {"handle": handle, "from": 1, "count": STATUS_PAGE},
                retry_once=retry_once)


def user_status(handle: str, *, pages: int = 20) -> list[dict]:
    """The handle's submissions, newest first, paging until a short page.

    Codeforces caps one page at STATUS_PAGE rows; the loop stops as soon as a
    page comes back short. `pages` is a safety bound, not a target.
    """
    submissions: list[dict] = []
    for page in range(pages):
        start = page * STATUS_PAGE + 1
        chunk = call("user.status",
                     {"handle": handle, "from": start, "count": STATUS_PAGE})
        submissions.extend(chunk)
        if len(chunk) < STATUS_PAGE:
            break
        pace()
    return submissions


# --- submission shape -------------------------------------------------------
# Every reader of user.status wants the same four things, and the JSON nests
# them differently in each case, so they are decoded here once.

ACCEPTED = "OK"


def submission_key(submission: dict) -> tuple[int, str] | None:
    """(contest id, problem index) for a submission, or None if it has neither."""
    contest_id = submission.get("contestId")
    index = submission.get("problem", {}).get("index")
    if contest_id is None or not index:
        return None
    return contest_id, index


def is_accepted(submission: dict) -> bool:
    return submission.get("verdict") == ACCEPTED


def is_contestant(submission: dict) -> bool:
    """True for in-contest submissions, false for practice-room ones."""
    return submission.get("author", {}).get("participantType") == "CONTESTANT"


def submitted_at(submission: dict) -> datetime | None:
    seconds = submission.get("creationTimeSeconds")
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)
