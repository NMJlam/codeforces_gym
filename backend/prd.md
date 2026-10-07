# Codeforces Gym — PRD (agent brief)

Personal training app. Picks Codeforces problems at a target solve chance, times each attempt strictly (45 min, no hints), and keeps a per-topic Glicko-style rating. Single user behind Cloudflare Access; `users` table allows a few more later.

**Governing rule:** only rate results where a failure would have been recorded too.

## Stack
Python (uv), Flask app factory + blueprints under `/api`, Flask-SQLAlchemy, Flask-Migrate, psycopg 3, PostgreSQL (Docker Compose on OrbStack). Config only in `config.py` from env: `DATABASE_URL`, `SECRET_KEY`, `CF_TEAM_DOMAIN`, `CF_AUD`, `AUTH_DISABLED` + `DEV_EMAIL` (dev only; app refuses to start if set outside `ENV=development`).

## Auth
`before_request` verifies `Cf-Access-Jwt-Assertion` (RS256, aud + iss checked, JWKS from `{CF_TEAM_DOMAIN}/cdn-cgi/access/certs`), sets `g.claims`, then `g.user = get_or_create_user(...)`. Routes use `g.user`; never re-query the user. No login/register/delete endpoints.

## Session flow
1. Start session → age RDs → weighted random topic draw.
2. Per slot, pick just in time: warm-up 80% → main 50% → stretch 25%. Failed warm-up → another warm-up.
3. Attempt: timer starts on open. **Done** = one CF API call (one retry) for an Accepted inside the window → S=1. **Give up** = S=0, no API call. Timer expiry enforced server-side: any call on an expired attempt scores it first. **Pause**/**Resume** freeze the clock while interrupted and restart it; paused time is added to the deadline, and a paused attempt never expires.
4. After scoring: rating update, calibration refit, return the editorial search string (no editorial flag exists), prompt key idea on failure, upsolve logged unrated.
5. Finish: save, set last-practised per topic, mark problems seen, queue a revisit 2–4 weeks out per failure.
6. Repeats: a failed problem comes back as an unrated repeat one week later, and again with a longer gap (7 → 21 → 45 → 90 days) every time it is failed again, until it is solved first try. The repeat takes the next pick's place and is not announced as a repeat while it is served; it never moves ratings or calibration.

## Rating model
- Topic rating = overall + `rating_offset`, each with RD.
- `E = 1 / (1 + 10^((problem − effective)/400))`. `P_cal = σ(a + b·logit(E))` used **only for picking**; updates use E.
- Update (q = ln10/400): `d² = 1/(q²E(1−E))`, `V = RD_o² + Σ w_t² RD_t²`, `gain = q(S−E)·d²/(V+d²)`; `overall += RD_o²·gain`; `offset_t += RD_t²·w_t·gain`; `RD² −= (RD²w)²/(V+d²)`.
- Tag weights normalised; generic tags (implementation, greedy, math, brute force, constructive algorithms) weight 0.25.
- RD aging on read, never written back: `RD² += 10²·days`; caps 350 overall / 150 topic; floors 45 / 55.
- New user 800 ± 350; new topic offset 0 ± 150. With contest history: contest rating + remaining newcomer bonus (+900/+550/+300/+150/+50 after 1–5 contests), then replay contest problems (solved=1, else 0).
- Calibration: refit a, b after each session attempt; priors a 0±0.5, b 1±0.5; half-life 100 attempts; `b > 0`.

## Picking
- Topic priority = relevance × (1 + weakness + staleness/2 + uncertainty/2); weakness 1.5 per 100 pts; relevance = `tier_weight` (interview relevance: 1.0 = core, 0.1 = competitive-programming only). Eligible: ≥3% of problems within ±200, ≥20 unseen near level, emergence rating reached. **No prerequisite gating**: a topic's difficulty comes from its rating, its reachability from `emergence_rating`, and RD uncertainty already drives exploration of untouched tags.
- Problem score (lowest wins), candidates within ±300 of target: `|P_cal − target| + 0.02·extra technique tags + 0.03·rarely solved`.
- Exclude: seen/submitted, Div1/Div2 twin, unrated. `*special` problems are never ingested. Codeforces exposes no editorial flag, so there is no "no editorial" filter — instead each problem carries `editorial_search` (`"{contest name} editorial"`) for the user to paste.

## Data (3 layers)
- **Catalog** (rebuildable from CF API): `problems` (rating `mod 100 = 0`; special problems are **not ingested** — no `is_special` column), `contests`, twin groups, `tag_groups` + `tags` (`group_id`, `emergence_rating`, `is_generic`, `tier_weight`), `problem_tags`.
- **Attempt log** (source of truth, back up daily): `users` (`email`, `cf_handle`), `sessions` (model `PracticeSession`, one open per user), `attempts` (`source`, `rated`; scored S immutable via trigger, key idea editable; `in_calibration = source='session' AND rated`; `accepted_submission_id` is CF's own id, a plain bigint), revisit queue.
- **Ratings** (rebuildable by replay): `overall_ratings`, `topic_ratings`, `calibration`; aging via `current_rd()`.
- **No submission cache**: CF submissions are read from the API on demand (Done check, external-solve sync); nothing is stored locally, so there is no `cf_submissions` table.
- **No settings**: `PUT /me` saves the CF handle only; the user row has no settings columns.
- Enforce rules in DB constraints/triggers. Schema changes only via migrations.

## API (`/api`)

User routes are mounted at `/api/users/...` (`GET /api/users/me`); sync routes at `/api/sync/...`.

| Route | Purpose |
|---|---|
| `GET /me` | user + overall rating ± aged RD (built) |
| `PUT /me` | save CF handle (built) |
| `POST /me/seed` | one-time rating seed (needs handle + catalog sync) |
| `POST /sessions` | start, draw topic |
| `GET /sessions/current` | open session, slots, results |
| `POST /sessions/{id}/next` | pick next slot's problem (optional `slot` overrides the sequence) |
| `POST /sessions/{id}/slots/{slot}/replace` | swap a seen pick (marked seen, unrated) |
| `POST /sessions/{id}/picks/{pick_id}/cancel` | back to the picker: drop an unopened pick, nothing recorded |
| `POST /sessions/{id}/finish` | save, last-practised, revisits |
| `POST /attempts` | open the picked problem, start the timer |
| `POST /attempts/{id}/done` | CF check, score, update |
| `POST /attempts/{id}/give-up` | S=0, update |
| `POST /attempts/{id}/pause` | freeze the timer; paused time never expires, does not count |
| `POST /attempts/{id}/resume` | restart it at where it stopped |
| `PATCH /attempts/{id}` | key idea, upsolve status |
| `GET /skills` | tag states (not yet relevant / unknown / weak / strong) + group ratings |
| `GET /history` | the attempt log, newest first; `q`/`page`/`per_page` search and page it |
| `POST /sync/catalog` | problems (skipping `*special`), tags, emergence (3% of ±200-smoothed share per bucket) (built) |
| `POST /sync/submissions` | outside solves → logged, seen, never rated |
| `POST /sync/contests` | replay new contests (Should) |

## Constraints
- Never poll Codeforces in the background; respect ~1 call / 2 s in sync jobs.
- No hints or tags shown during an attempt.
- Pick returns < 1 s on ~10k problems.
- Rating and pick logic as pure functions with unit tests + a simulation harness.

## Non-goals
Hints, partial credit, time-based scores, in-app editor/judge, public sign-up, social features, app-level login.

## Build order
Auth + `GET /me` (done) → `PUT /me` (done) → catalog sync (done) → `POST /me/seed` → rating engine proven in simulation → sessions/attempts.

## Open questions
Ending early (started = 0, unopened = not recorded?); frontend (Flask templates vs React/Vite); contest replay discount (d² × 1.5?); backup location.

- Rename `tier_weight` → `interview_weight`? The column is interview relevance, not a difficulty tier.
- `PUT /me` once seeded: allow a stale handle, `409`, or auto-reseed?
- Auth: `get_or_create_user` (as specified above) vs the current 403 for an unknown email?
- Stack: no `config.py` yet — env is read inline and the audience var is `CF_ACCESS_AUD`, not `CF_AUD`; `SECRET_KEY`/`DEV_EMAIL`/`ENV` guard are unimplemented.
- Tag groups: PRD mentions 8; `0002` defines 9 (`Games` included).
