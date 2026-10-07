# Slotline

Multi-tenant booking API (FastAPI + Postgres 17) that can never double-book a provider,
plus a worker for holds, reminders, waitlist offers and signed webhooks.

**Read before any change:** `docs/plan.md` (the spec) and `docs/architecture.md` (how it flows).
Log of finished sessions: `docs/progress.md`. Read its last entry at the start of every session.

## Commands
- `make dev`       — API on :8000 with reload (Swagger at /docs)
- `make worker`    — run the worker process
- `make test`      — all tests (needs `docker compose up -d postgres redis mailpit`)
- `make lint`      — ruff check + ruff format --check + mypy --strict
- `make migrate`   — alembic upgrade head
- `make seed`      — demo clinic data

## How we work
- One session = one PR = one row of the 12-session table in `docs/plan.md`.
- **First reply is always a plan:** files you'll create or change, the tests you'll add, and
  anything in the plan you think is wrong or unclear. Then stop and wait for my OK.
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).

## Branches (full rules: `docs/BRANCHING.md`)
- Flow: `feature/*` → `dev` → `uat` → `release` → `main`. **`release` is production**;
  `main` is the stable record, updated only after a release proves stable.
- Session work: branch from the latest `dev` as `feature/s<NN>-<short-name>`
  (e.g. `feature/s06-bookings-core`); other changes use `fix/`, `docs/` or `chore/`.
  Open the PR with base **`dev`**. Never target `uat`, `release` or `main` from a feature branch.
- Never commit or push directly to `dev`, `uat`, `release` or `main`, and never merge PRs. I merge.
- Promotions (`dev`→`uat`→`release`→`main`) and hotfixes happen only when I ask, as PRs
  between those branches, never squashed or rebased. Hotfixes branch from `release` and
  target `release`; afterwards back-merge `release` into `uat` and `dev`.
- Workflows that deploy: `uat` branch → UAT environment, `release` branch → production.
  `main` never deploys.
- Before saying a task is done: `make lint && make test` pass. Paste the summary lines in the PR.
- PR description: what changed, why, how to test it, test output, and **"Things to understand"**:
  3–5 bullets on the trickiest code in the PR, written so a junior engineer could explain them.
- Ask me before adding a dependency, changing the public API shape, or deviating from `docs/plan.md`.
  If we agree to deviate, update `docs/plan.md` or add an ADR in the same PR.

## Architecture rules
- Layering: `api/` → `services/` → `repositories/`. Routes handle HTTP only. Services own
  transactions (`async with uow:`); routes never call `commit`.
- `domain/` is pure Python: no FastAPI, SQLAlchemy, or I/O imports. Hardest logic lives here.
- Every repository method takes `org_id` as its first argument. Never query without it.
  The tenant always comes from the credential, never from the URL or body.
- Another tenant's ID returns **404**, never 403.
- Never check availability with SELECT before INSERT. Rely on the `bookings_no_overlap`
  exclusion constraint and map SQLSTATE `23P01` to `409 slot_unavailable`.
- Inside a booking transaction, expire stale holds for the range first (plan rule 3).
- Booking status changes go through `domain/booking_state.py` and write a `booking_events` row.
- Side effects (email, webhooks) never happen in the request: write an `outbox_events` row
  in the same transaction; the worker does the rest.
- Every job handler is idempotent and has a `dedupe_key`.
- No `datetime.now()` outside `clock.py`; inject `Clock`. Store UTC; convert only at edges.
- All errors are Problem Details (RFC 9457) with a stable `code` from `errors.py`.
- Every new endpoint: Pydantic schemas, Problem Details errors, and tests for success,
  validation, auth, and another tenant's IDs.
- New Alembic migration for every model change; never edit a merged migration.
  Expand-then-contract: never rename or drop a column in one step.

## Testing rules
- Tests use the real Postgres container. Never SQLite, never mocking the database.
- Concurrency tests are marked `@pytest.mark.concurrency` and use separate connections.
- Coverage: 85% overall, 95% for `services/` and `domain/`.

## Never
- Commit secrets, `.env`, tokens or real customer data.
- Log full tokens, API keys, emails or phone numbers (mask to last 4).
- Disable a failing test or lower a coverage threshold to make CI pass. Tell me instead.
