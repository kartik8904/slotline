# Slotline

A multi-tenant booking API for clinics and salons that **cannot double-book a provider**,
with the background automation a real booking product needs: expiring holds, reminders,
waitlist offers and signed webhooks.

> Status: in development. Built in 12 sessions; see `docs/progress.md`.

## Docs

Read in this order:

| # | Read this | For |
| --- | --- | --- |
| 1 | [docs/PROJECT-OVERVIEW.md](docs/PROJECT-OVERVIEW.md) | What Slotline is, who uses it, features, known gaps |
| 2 | [docs/architecture.md](docs/architecture.md) | How the API, worker and Postgres fit together (diagrams) |
| 3 | [docs/BRANCHING.md](docs/BRANCHING.md) | Branch flow: feature → dev → uat → release → main |
| 4 | [docs/LOCAL-SETUP.md](docs/LOCAL-SETUP.md) | Clone and run on your Mac with Claude Code |
| 5 | [docs/START-HERE.md](docs/START-HERE.md) | Cloud setup and the per-session loop |
| 6 | [docs/session-prompts.md](docs/session-prompts.md) | Prompt for each build session and each promotion |
| — | [docs/plan.md](docs/plan.md) | Full specification |
| — | [docs/progress.md](docs/progress.md) | What's been built so far |

## Branches

| Branch | Purpose |
| --- | --- |
| `dev` (default) | Integration; every feature PR lands here |
| `uat` | Testing; deploys to UAT |
| `release` | **Production**; deploys after approval |
| `main` | Stable record of releases proven in production |

## Stack

Python 3.13 · FastAPI · Pydantic v2 · PostgreSQL 17 (btree_gist) · SQLAlchemy 2 async ·
Alembic · Redis · structlog · OpenTelemetry · pytest + Hypothesis + Schemathesis ·
Docker · GitHub Actions

## Run locally

Needs Python 3.13, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env                              # local config, never committed
docker compose up -d postgres redis mailpit       # Postgres 17, Redis 7, Mailpit
uv sync                                           # install dependencies
make migrate                                      # alembic upgrade head
make dev                                          # API on :8000, Swagger at /docs
```

Other commands: `make test`, `make lint`. `docker compose up` starts the whole stack except
the worker, which is a placeholder until session 8 (`docker compose --profile worker up`).
Mailpit's inbox is at http://localhost:8025.

## Results

_Filled in at session 12._

| Claim | How it's measured | Result |
| --- | --- | --- |
| No double bookings | 200 concurrent holds on one slot | |
| Safe retries | 50 identical requests, one idempotency key | |
| Hold latency | p95 at 50 requests/second | |
| Availability latency | p95, 7 days × 3 providers | |
| Automation reliability | 2 workers, 500 jobs, each exactly once | |
| Test coverage | pytest-cov on release | |
