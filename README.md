# Slotline

A multi-tenant booking API for clinics and salons that **cannot double-book a provider**,
with the background automation a real booking product needs: expiring holds, reminders,
waitlist offers and signed webhooks.

> Status: in development. Built in 12 sessions; see `docs/progress.md`.

## Docs

| Read this | For |
| --- | --- |
| [docs/PROJECT-OVERVIEW.md](docs/PROJECT-OVERVIEW.md) | What Slotline is, who uses it, features, known gaps |
| [docs/START-HERE.md](docs/START-HERE.md) | Setting up and building with Claude cloud sessions |
| [docs/architecture.md](docs/architecture.md) | How the API, worker and Postgres fit together (diagrams) |
| [docs/plan.md](docs/plan.md) | Full specification |
| [docs/session-prompts.md](docs/session-prompts.md) | Prompts for each build session |
| [docs/progress.md](docs/progress.md) | What's been built so far |

## Stack

Python 3.13 · FastAPI · Pydantic v2 · PostgreSQL 17 (btree_gist) · SQLAlchemy 2 async ·
Alembic · Redis · structlog · OpenTelemetry · pytest + Hypothesis + Schemathesis ·
Docker · GitHub Actions

## Run locally

_Filled in after session 1._

## Results

_Filled in at session 12._

| Claim | How it's measured | Result |
| --- | --- | --- |
| No double bookings | 200 concurrent holds on one slot | |
| Safe retries | 50 identical requests, one idempotency key | |
| Hold latency | p95 at 50 requests/second | |
| Availability latency | p95, 7 days × 3 providers | |
| Automation reliability | 2 workers, 500 jobs, each exactly once | |
| Test coverage | pytest-cov on main | |
