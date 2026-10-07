# Codeforces Gym — task runner. Run `just` to list recipes.
#
# The recipes up to "Host-only dev" are local development: the Compose services
# are dev images (bind mounts, Flask --debug, Vite HMR). The `prod-*` recipes
# run the homelab stack from docker-compose.prod.yml — see README.md, Deploying.

# List recipes.
default:
    @just --list

# ---- Setup --------------------------------------------------------------

# Install host toolchains: backend into backend/.venv, frontend into node_modules.
install:
    cd backend && uv sync --frozen
    cd frontend && bun install --frozen-lockfile

# Create backend/.env from the example, if absent.
env:
    @test -f backend/.env || { cp backend/.env.example backend/.env; echo "wrote backend/.env"; }

# ---- Compose (backend + frontend + db) ----------------------------------

# Build and start everything. Frontend http://localhost:5173, backend :5001.
up: env
    docker compose up -d --build

# Stop and remove containers (the postgres_data volume is kept).
down:
    docker compose down

# Rebuild and restart.
restart: down up

# Tail logs for all services, or one: `just logs backend`.
logs +services="":
    docker compose logs -f {{ services }}

# Show service status.
ps:
    docker compose ps

# ---- Database -----------------------------------------------------------

# Start only PostgreSQL and wait until it accepts connections.
db:
    docker compose up -d db
    cd backend && until docker compose exec db pg_isready -U postgres -d codeforces_gym_db >/dev/null 2>&1; do sleep 0.3; done
    @echo "postgres ready"

# Apply migrations up to head.
migrate: db
    cd backend && uv run flask --app app db upgrade

# New migration from model changes. Read the generated file before `just migrate`.
revision message:
    cd backend && uv run flask --app app db migrate -m "{{ message }}"

# Fetch problems/tags/contests from the Codeforces API (needs the schema).
catalog:
    cd backend && uv run python -m scripts.populate_codeforces

# Fill the dev user with fake practice history so the UI has data (dev only).
seed:
    cd backend && uv run python -m scripts.seed_fake_data

# ---- Checks -------------------------------------------------------------

# Backend test suite (needs the db service running and the catalog synced).
test: db
    cd backend && uv run pytest -q

# Frontend type/lint check.
check:
    cd frontend && bun run check

# Production build of the frontend, into frontend/build (sanity-check that it compiles).
# --bun keeps the Vite/SvelteKit CLI on Bun's runtime: the postbuild worker uses
# Promise.withResolvers, which the node on a dev machine may well be too old for.
build:
    cd frontend && bun --bun run build

# Prove the app loads and list its routes.
routes:
    cd backend && uv run flask --app app routes

# Rating-model simulation; exits nonzero if the median error exceeds tolerance.
simulate seed="1" users="100" attempts="1000":
    cd backend && uv run python scripts/simulate_rating.py --seed {{ seed }} --users {{ users }} --attempts {{ attempts }}

# ---- Production (homelab, behind a Cloudflare Tunnel) -------------------

# Create .env.prod from the example, if absent.
prod-env:
    @test -f .env.prod || { cp .env.prod.example .env.prod; echo "wrote .env.prod — fill in the blanks"; }

# Build and start the production stack. Nothing is published except the loopback
# debug port 8080; cloudflared is what makes it reachable.
prod-up: prod-env
    docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# Stop the production stack (the postgres_data volume is kept).
prod-down:
    docker compose -f docker-compose.prod.yml --env-file .env.prod down

# Rebuild and restart the production stack.
prod-restart: prod-down prod-up

# Tail production logs, or one service: `just prod-logs backend`.
prod-logs +services="":
    docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f {{ services }}

# Show production service status, including healthchecks.
prod-ps:
    docker compose -f docker-compose.prod.yml --env-file .env.prod ps

# Apply migrations by hand. The backend entrypoint already does this on start;
# this is for recovering a stack that is up but behind the schema.
prod-migrate:
    docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend flask --app app db upgrade

# Refresh problems/tags/contests from Codeforces, inside the stack. The
# production database has no published port, so this cannot run from the host.
prod-catalog:
    docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T backend python -m scripts.populate_codeforces

# Dump the production database, gzipped and timestamped, into backups/.
prod-backup:
    @mkdir -p backups
    docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db pg_dump -U postgres codeforces_gym_db | gzip > backups/gym-$(date +%Y%m%d-%H%M%S).sql.gz
    @ls -lht backups | head -3

# psql shell into the production database.
prod-db:
    docker compose -f docker-compose.prod.yml --env-file .env.prod exec db psql -U postgres -d codeforces_gym_db

# ---- Host-only dev (no Docker for the app) ------------------------------

# Run the backend on the host (needs `just db` for PostgreSQL).
dev-backend:
    cd backend && uv run flask --app app run --host 0.0.0.0 --port 5001 --debug

# Run the frontend on the host, proxying /api to the backend.
dev-frontend:
    cd frontend && bun run dev
