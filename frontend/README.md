# frontend

SvelteKit 3 (client-only SPA, `ssr = false`) + Tailwind 4 + shadcn-svelte
components. Charts come from `layerchart`. It talks to the Flask service under
`/api` and holds no state of its own: every number on screen is a fresh read.

## Running it

```sh
just up                       # from the repository root: frontend on :5173
```

Or on the host, against a backend you are already running:

```sh
bun install
bun run dev                   # proxies /api to API_URL, default http://localhost:5001
API_URL=http://localhost:5002 bun run dev --port 5199
```

`vite.config.ts` proxies `/api`, which is what makes the relative `fetch` calls
in `src/lib/api.ts` work in development. Cloudflare Access supplies the JWT in
production, so no token handling exists in the client.

## Pages

Two top-level pickers and nothing else: **Session** (the practice flow) and
**Profile** (everything about the account). `/` redirects to the dashboard, and
the profile carries a slider for its four tabs.

| Route | What it shows |
|---|---|
| `/session` | the whole flow, behind a picker: **Recommended** (start, pick, open with the 45-minute countdown, pause/resume, Done/give up, notes, finish) or **Self-picked** (bring your own problem id) |
| `/profile/dashboard` | rating ± RD, today's session, the activity calendar, topic radars, rating over time |
| `/profile/topics` | every tag's rating, RD and state (`weak`/`strong`/`unknown`/`not yet relevant`) |
| `/profile/history` | sessions with their attempts, plus a flat attempt table |
| `/profile/setup` | Codeforces handle, one-time seeding, catalog/submission/contest syncs |

## Layout

- `src/lib/api.ts` — the API contract: types, paths, request bodies and the
  words shown when a request is refused. Components never call `fetch`
  directly, so an error message only has to be good in one place.
- `src/lib/current-session.svelte.ts` — the open session and the attempt being
  timed, shared by the dashboard and the session page.
- `src/lib/format.ts` — countdown/date/chance formatting.
- `src/lib/components/segmented-nav.svelte` — the pickers: equal-width links
  with a pill that slides under the active one. It reads the route itself, so
  the two top-level pickers and the profile slider are the same component.
- `src/lib/components/contribution-graph.svelte` — the GitHub-style activity
  calendar on the dashboard. A pure view of `GET /history`: one square per
  local day, one column per week, shaded by that day's attempt count.
- `src/lib/components/` — `attempt-card`, `problem-line` and small UI
  primitives (`button`, `panel`, `badge`, `input`, `textarea`) in the same
  Tailwind style as the vendored `ui/tabs` and `ui/table` components. Tables use
  `Table.Root variant="card"` for the separated-border, rounded-row look.

## Rules the UI keeps

- **No hints during an attempt.** A problem's tags are never sent by the API,
  and the editorial search string only appears once the attempt is scored — the
  pick card deliberately has neither.
- **Notes stay out of the way.** The key-idea box is collapsed on every card,
  failed attempts included — the result panel already asks for it — and it
  closes itself once the idea is saved.
- **The timer is the server's.** The countdown is a view of the attempt's
  `deadline`; when it reaches zero the client re-reads the session and lets the
  backend score the run-out attempt, because every endpoint that touches an
  attempt scores an expired one first.
- **Pausing is the server's too.** Pause/Resume only move the attempt's
  `paused_at`; a paused timer never expires, the countdown freezes at that
  instant, and resuming extends the deadline by exactly the time spent paused.
- **After any mutation, re-read.** Actions refresh from the server rather than
  patching local state, so a pick, a score or a sync can never disagree with the
  database.
- **An open attempt is never lost.** A picked-but-unopened problem and a
  self-selected attempt (which has no session) are both recovered on load, the
  latter from the attempt log, because an invisible open attempt would block
  starting a session.

## Checks

```sh
bun run check        # svelte-kit sync + svelte-check
bun --bun run build  # production build, into build/
```

`--bun` matters: without it the Vite CLI runs under whatever `node` is on PATH,
and the SvelteKit postbuild worker needs `Promise.withResolvers` (Node 22+). Bun
has it either way, which is why the Docker build never hits this.

The adapter is `adapter-static` with a `fallback`, because every page is client
rendered: `build/index.html` is the shell that nginx serves for any route (see
`nginx.conf` and `Dockerfile.prod`).
