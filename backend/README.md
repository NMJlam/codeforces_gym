# backend

Flask + SQLAlchemy + Flask-Migrate service. PostgreSQL is **required**: the
models use check constraints, generated columns, intervals, and partial indexes
that SQLite cannot express, so there is no SQLite fallback.

## Local setup

```sh
cp .env.example .env      # DATABASE_URL points at the repo Compose database
uv sync
```

Start PostgreSQL from the **repository root** (the Compose file lives there, not
here):

```sh
docker compose up -d db
docker compose exec db pg_isready -U postgres -d codeforces_gym_db
```

Wait for `accepting connections` before running any migration command.

Create the schema:

```sh
uv run flask --app app db upgrade
```

Every command below also runs from this directory (`backend/`), because
`flask --app app` imports `app.py` here.

## Configuration

`config.py` is the only reader of `os.environ`; `create_app()` copies its result
into Flask config. `.env` is loaded first (relative to `app.py`), so local
development needs no exported variables, and real environment variables win.

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | required; PostgreSQL URL (`postgresql+psycopg://…`) |
| `SECRET_KEY` | required; Flask's session signing key |
| `ENV` | `development` or unset/`production` |
| `AUTH_DISABLED` | `1`/`true`/… skips Cloudflare Access. **Refused unless `ENV=development`** |
| `DEV_EMAIL` | required when `AUTH_DISABLED` is on: who the dev request acts as |
| `CF_TEAM_DOMAIN` | required when auth is enabled; the Access team URL |
| `CF_AUD` | required when auth is enabled; the Access application audience |

The app refuses to start on a contradictory environment (missing required
variables, dev auth outside development, dev auth without `DEV_EMAIL`) rather
than failing on the first request that needs one.

## API (`/api`)

| Route | Purpose |
|---|---|
| `GET /users/me` | user + overall rating ± aged RD, group ratings, past year, `seeded` |
| `PUT /users/me` | save the CF handle (409 once ratings are seeded) |
| `POST /users/me/seed` | one-time rating seed from the handle's CF history |
| `POST /sessions` | start a session, draw one eligible topic |
| `GET /sessions/current` | the open session: picks, results, next slot |
| `POST /sessions/{id}/next` | pick the next slot's problem (timer not started), or a due repeat; optional `{"slot": "warmup"|"main"|"stretch"}` overrides the session's own sequence |
| `POST /sessions/{id}/slots/{slot}/replace` | swap a pick: old problem marked skipped, unrated |
| `POST /sessions/{id}/picks/{pick_id}/cancel` | go back to the picker: drop an unopened pick, nothing recorded |
| `POST /sessions/{id}/finish` | close, mark seen, queue revisits for failures |
| `POST /attempts` | open a picked (`pick_id`) or self-selected (`problem_id`) problem |
| `POST /attempts/{id}/done` | one CF call (one retry), score S=1 on an in-window Accepted |
| `POST /attempts/{id}/give-up` | score S=0, no CF call |
| `POST /attempts/{id}/pause` | freeze the timer while interrupted; idempotent |
| `POST /attempts/{id}/resume` | restart it; the paused time does not count against the 45 minutes |
| `PATCH /attempts/{id}` | key idea / upsolve flag only; never score or rating |
| `GET /skills` | per-tag state (`not_yet_relevant`/`unknown`/`weak`/`strong`) + group ratings |
| `GET /history` | sessions and attempts, newest first |
| `POST /sync/catalog` | problems, tags, contest metadata, tag emergence |
| `POST /sync/submissions` | outside solves → seen (reason `external`), never rated |
| `POST /sync/contests` | replay entered contests that have no attempts yet |

No route ever returns a problem's tags, and a pick never carries the editorial:
the editorial only appears once the attempt has been scored.

## Repeats

A failed problem is not finished with. `finish` queues the same problem as a
`recall` revisit a week out, and `next` serves it before any fresh pick. Failing
it again queues the next one further out (7 → 21 → 45 → 90 days, then 90
forever), so a problem keeps coming back until it is solved first try.

A repeat is unrated: no rating update, no calibration refit, and it does not
count as new evidence in the picker. It is also not announced. While the repeat
is being served, `slot` reads as `warmup` in picks and in open attempts — the
real `recall` slot only shows up in the attempt's history once it is scored.
Its chance and target probability are still honest numbers, so the payload of a
repeat is indistinguishable from an ordinary warm-up.

The picker's other follow-up, `related` (an unseen problem with matching tags at
a similar rating, rated), is queued 2-4 weeks out and is not served yet.

## Rating model

The model itself is pure (`rating.py`): no ORM, no Flask, no network.
`scoring.py` is the only bridge that writes attempts, ratings and seen rows, so
the snapshot fields (`e_model`, `problem_rating`, `effective_rating`,
`overall_after`), the normalised `AttemptTag` weights and the rating update can
never drift apart between the seed, session, contest-sync and submissions-sync
paths.

```sh
uv run pytest -q                                   # model + route contracts
uv run python scripts/simulate_rating.py --seed 1 --users 100 --attempts 1000
```

The simulation harness fits nothing to the database: it simulates users with a
fixed latent skill, feeds scored attempts through `rating.update_rating`, and
exits nonzero when the median final rating error exceeds its documented
tolerance. It fixes the gauge (topic offsets are pinned to zero mean) because
the overall rating and the average topic offset are not separately identifiable
from attempts alone.

## Day-to-day commands

```sh
uv run flask --app app routes   # sanity check that the app loads
uv run flask --app app db current
uv run flask --app app db check # is the DB at the migrations' head state?
uv run python -m scripts.seed_fake_data # fake practice history for the dev user (dev only)
```

## Changing the models

1. Edit the model files in `model/`. A new model file must also be imported in
   `model/__init__.py`, or Alembic will not see its table.
2. Generate a revision:

   ```sh
   uv run flask --app app db migrate -m "short description"
   ```

3. **Read the generated file** in `migrations/versions/` and fix anything
   autogenerate gets wrong (data migrations, triggers, index changes it cannot
   infer). Only then apply it:

   ```sh
   uv run flask --app app db upgrade
   ```

The repository numbers its revisions `0001`…`NNNN`; rename the generated file
and its `revision` to keep that. Downgrades use
`uv run flask --app app db downgrade <revision>`.

`migrations/` is committed. Never run `db init` again — the repository already
exists, and re-running it would overwrite `migrations/env.py`'s wiring.

## Notes

- `DATABASE_URL` (and `SECRET_KEY`) are required; `config.load_config()` raises
  `ConfigError` without them.
- `.env` is loaded relative to `app.py`, so the working directory does not
  matter. Real environment variables take precedence over `.env`.
- Schema details that models cannot express live in the migrations; the scored
  attempt fields (`s`, `e_model`, `scored_at`) are frozen by the
  `trg_attempts_score_immutable` trigger created in the initial revision.
- A user's Codeforces handle is set once (`PUT /users/me`). After seeding it is
  locked (409) because the seeded history belongs to that specific account.
