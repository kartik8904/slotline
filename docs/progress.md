# Progress log

One entry per merged session, newest first. Claude reads the latest entry at the start of
every session; you read the "What I should understand" lists before interviews.

| # | Session | Status | PR |
| --- | --- | --- | --- |
| 1 | Skeleton | In review | #3 |
| 2 | CI | Not started | |
| 3 | Tenancy and auth | Not started | |
| 4 | Catalogue | Not started | |
| 5 | Availability | Not started | |
| 6 | Bookings core | Not started | |
| 7 | Lifecycle and safety | Not started | |
| 8 | Worker | Not started | |
| 9 | Notifications | Not started | |
| 10 | Waitlist and webhooks | Not started | |
| 11 | Observability and hardening | Not started | |
| 12 | Ship it | Not started | |

---

## Setup — repository organised (2026-10-07)

**Built:**
- Docs moved under `docs/`; `.claude/settings.json`, PR template and `.gitignore` in place
- `docs/plan.md` added from the Slotline Build Plan doc, updated for the branch flow
- Branch flow feature → dev → uat → release → main (`docs/BRANCHING.md`), enforced by `.github/workflows/branch-flow.yml`
- Branches `dev`, `uat`, `release` created from `main`

**Decisions:**
- `release` deploys to production; `main` is the stable record, updated after a release proves stable; hotfixes go into `release` (BRANCHING.md, plan.md updated)

- Session 0 review (7 Oct): 18 gaps settled as Clarifications C1–C18 in `docs/plan.md` (login, lockout, duplicate customers, hold expiry exactly-once, idempotency crash safety, Redis fail-open, SSRF at delivery, session splits)

**Carried forward / TODO:**
- Set `dev` as default branch and add rulesets (manual, `docs/START-HERE.md` section 2)
- Decide the known gaps in `docs/PROJECT-OVERVIEW.md` section 14 before sessions 3, 7, 9

## Session 1 — Skeleton (2026-10-07)

**PR:** https://github.com/kartik8904/slotline/pull/3

**Built:**
- uv project (Python 3.13), `src/slotline` layout, `create_app()` with pydantic-settings config
- `GET /api/v1/health/live` and `/health/ready` (Postgres required, Redis reported only, per C12)
- structlog JSON logging (`logging_config.py`), `X-Request-ID` middleware with one access-log line per request
- Problem Details handlers and `errors.py` codes; injectable `Clock` (`clock.py`)
- Alembic (async, empty baseline `0001`), Makefile, `compose.yaml` (worker behind a `worker` profile), multi-stage non-root Dockerfile, `.env.example`, pre-commit
- pytest against the real Postgres container; coverage gate `fail_under = 85` is on from day one

**Decisions** (plan.md / ADR updated?):
- Readiness follows C12 (Postgres only); no plan change needed
- Added error code `service_unavailable` (503) for failed readiness; not in the plan's error table, so add it when plan.md is next edited
- Request IDs are `req_<uuid4 hex>` (no UUIDv7 in Python 3.13); inbound IDs kept if `[A-Za-z0-9._-]{1,128}`
- `btree_gist` is enabled by `docker/postgres/init.sql` locally; session 6's migration must also `CREATE EXTENSION IF NOT EXISTS btree_gist`
- Dependencies added: fastapi, uvicorn, pydantic-settings, sqlalchemy, asyncpg, alembic, redis, structlog; dev: pytest, pytest-asyncio, pytest-cov, httpx, ruff, mypy, pre-commit

**Carried forward / TODO:**
- Session 8: remove the `worker` profile from `compose.yaml`
- Session 2: CI; the access log's `route` field shows the router-relative path (`/health/live`), tidy if it matters
- `.pre-commit-config.yaml` not run in this session; run `uv run pre-commit install` locally

**What I should understand:**
1. Plain ASGI middleware — `BaseHTTPMiddleware` breaks contextvars and hides exceptions, so request IDs use a raw ASGI class
2. The 500 handler lives outside our middleware — so it sets `X-Request-ID` itself
3. `create_app()` factory — uvicorn runs it with `--factory`; no import-time app, so tests build apps with their own Settings

<!-- Entry template — copy above this line for each session

## Session N — <name> (YYYY-MM-DD)

**PR:** <link>

**Built:**
-

**Decisions** (plan.md / ADR updated?):
-

**Carried forward / TODO:**
-

**What I should understand:**
1. <concept> — <one-line explanation>

-->
