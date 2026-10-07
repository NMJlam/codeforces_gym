# Codeforces Gym

This is a training app for Codeforces that I use on my own. It picks a problem
you have a decent chance of solving, gives you 45 minutes with no hints, and
then updates a rating for each topic. Over time it learns which topics you are
weak at (or which it isn't sure about yet) and sends more of those your way.

It's built with:

- **Backend:** Python 3.13, Flask, SQLAlchemy and PostgreSQL.
- **Frontend:** SvelteKit 5 running as a plain single page app, with Tailwind 4
  and shadcn-svelte.
- **Dev setup:** one `docker-compose.yml` that runs PostgreSQL 17, the Flask
  dev server and Vite.

If you want more detail, [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md) cover each side, and
[`backend/prd.md`](backend/prd.md) has the full spec (how the rating works, how
problems get picked, how a session flows).

## What you need

- [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh/)
- Docker with Compose v2. On macOS, [OrbStack](https://orbstack.dev/) works well.

## Getting started

```sh
just install          # install Python and JS dependencies
just up               # build and start the db, backend and frontend
just migrate          # create the database tables
just catalog          # pull problems, tags and contests from Codeforces
just seed             # optional: add some fake practice history
```

Once it's up:

- Frontend: <http://localhost:5173>
- Backend: <http://localhost:5001>
- PostgreSQL: `127.0.0.1:5434` (I used 5434 because 5432 and 5433 are usually
  taken already)

Locally you don't need to log in. The dev setup sets `AUTH_DISABLED=1` and a
`DEV_EMAIL` (see `backend/.env.example`), so the app just treats you as that
user. In production, Cloudflare Access sits in front and the backend checks its
login token on every request.

If you'd rather run the app on your machine and only keep the database in
Docker:

```sh
just db               # start PostgreSQL in Docker
just dev-backend      # run Flask locally
just dev-frontend     # run Vite locally (it forwards /api to localhost:5001)
```

## Checking things work

```sh
just test             # backend tests (needs the db running and the catalog synced)
just check            # type check the frontend
just build            # build the frontend for production
just routes           # make sure the app loads and list its routes
just simulate         # run the rating simulation
```

The rating maths gets tested by simulation as well as unit tests.
`just simulate` creates fake users with a known skill level, runs them through
lots of problems, and fails if the ratings it ends up with are too far from
their real skill.

Run `just` on its own to see every command.

## Deploying

It runs on a homelab behind a **Cloudflare Tunnel**, so nothing is port-forwarded
and Cloudflare Access does the login: the backend's only identity source is the
`Cf-Access-Jwt-Assertion` header the tunnel's edge adds to every request.

`docker-compose.prod.yml` is that stack — Postgres, gunicorn, nginx and
cloudflared — and the dev files are untouched.

```sh
cp .env.prod.example .env.prod   # POSTGRES_PASSWORD, SECRET_KEY, CF_TEAM_DOMAIN, CF_AUD, TUNNEL_TOKEN
just prod-up                     # build + start; data volume starts empty
just prod-ps                     # healthchecks, including the tunnel
```

In the Cloudflare dashboard, point the tunnel's public hostname at
`http://frontend:80`, and put an Access application on that hostname. nginx
serves the built SPA and proxies `/api` to the backend on the same origin, which
is why the client's relative `fetch` calls keep working outside Vite.

What the images do differently from the dev ones:

- **Backend** (`backend/Dockerfile.prod`): gunicorn under a non-root user, no
  debugger, and `entrypoint.sh` applies migrations before serving — a fresh
  volume has no schema otherwise. `ENV=production` is set and `AUTH_DISABLED` is
  absent, so `config.py` refuses to start on a contradictory environment rather
  than silently serving every request as one user. `/healthz` is outside `/api`,
  so the healthcheck needs no Access token.
- **Frontend** (`frontend/Dockerfile.prod`): `bun run build` with
  `adapter-static` into nginx. The app is client-rendered, so the adapter emits
  the shell as `index.html` and nginx serves it for every route.
- **Syncs are slow on purpose**: they pace Codeforces at ~1 call / 2 s and page
  up to 20 times, so nginx and gunicorn both allow 300 s and the gunicorn worker
  is threaded to keep the rest of the app answering meanwhile.

Still on you, because no file in the repo can do it:

- **Backups.** One disk, one database. `just prod-backup` gzips a `pg_dump` into
  `backups/`; put that on a timer and copy the result off the box.
- **Refreshing the catalog.** `just prod-catalog` (or the Sync catalog button on
  the setup page). The production database has no published port, so the host
  cron cannot reach it — everything must go through the stack:
  `0 3 * * 0 cd /path/to/repo && just prod-catalog`.
- **Committing.** The repository has no commits yet, so there is nothing to roll
  back to when a deploy goes wrong.
