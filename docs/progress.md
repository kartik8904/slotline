# Progress log

One entry per merged session, newest first. Claude reads the latest entry at the start of
every session; you read the "What I should understand" lists before interviews.

| # | Session | Status | PR |
| --- | --- | --- | --- |
| 1 | Skeleton | Done | #3 |
| 2 | CI | Done | #4 |
| 3 | Tenancy and auth | In review | |
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

## Session 3 — Tenancy and auth (2026-10-07)

**PR:** (link after opening)

**Built:**
- Migration `0002` and models: `organizations`, `users`, `refresh_tokens`, `api_keys` (UUID v7 ids, `org_id`, timestamps); `ids.py` generates UUID v7 (Python 3.13 has none)
- argon2id passwords (hashed off the event loop), HS256 access JWTs (15 min, `kid` header, key rotation), rotating 30-day refresh tokens in families, `sl_live_` API keys stored as SHA-256 hashes
- Endpoints: `/auth/signup|login|refresh|logout`, `GET /me`, `POST /me/password`, `/api-keys` (owner), `/users` (owner); cursor pagination on both lists
- `UnitOfWork`, org-scoped repositories, `repositories/credential_lookup.py` (the only pre-tenant queries), services, `deps.current_principal` (Bearer or `X-API-Key` → `Principal`), `require_owner`, `require_scope`, and a no-op `login_rate_limit` hook for session 7
- Lockout (C2/C20) as a pure function in `domain/lockout.py`; `ENVIRONMENT` is now required and production needs real JWT keys (C24)
- Tests: unit (ids, lockout, passwords, tokens, keys, config, repository scan), integration for every endpoint, a tenant-isolation scaffold generated from the OpenAPI spec, and concurrency tests (parallel refresh, parallel wrong passwords, two owners demoting each other, parallel signups)

**Decisions** (plan.md / ADR updated?):
- Plan clarifications C19–C28 added to `docs/plan.md` (staff passwords and `POST /me/password`, lockout window column, credential lookups, new error codes `email_exists` and `last_owner`, key scopes, environment and JWT keys, what a request trusts, strict refresh reuse, email and password rules, deactivation); plan tables and the error table updated
- Dependencies added: `argon2-cffi`, `PyJWT` (both named in the plan's stack table)
- `ci.yml` sets `ENVIRONMENT: test` for every job (it is required now)
- `[tool.coverage.run] concurrency = ["greenlet", "thread"]` added: SQLAlchemy's async engine runs on greenlets, and without it coverage under-reported `services/` at about 65% when the real figure is above 95%. No threshold was changed.

**Carried forward / TODO:**
- Session 7: replace the body of `login_rate_limit` with the Redis limiter (also applied to signup); signup is open until then (C22)
- Sessions 4+: register new path-parameter names in `ORG_B_IDS` and bodies in `SAMPLE_BODIES` in `tests/integration/test_tenant_isolation.py`; IDs in bodies or query strings need the scaffold extended
- Session 9: email-based password reset and invites (C19); customer-facing tokens
- Set `JWT_KEYS` and `JWT_ACTIVE_KID` in the UAT and production secret stores before session 12 deploys (the app won't start without them)

**What I should understand:**
1. Commit, then raise — a failed login or a reused refresh token must still write (the failure count, the family revocation), but raising inside `async with uow:` rolls back; so the service records the outcome in the block and raises after leaving it
2. Atomic refresh rotation — one `UPDATE … WHERE revoked_at IS NULL RETURNING` decides the winner among parallel requests; every loser finds the token already revoked, which is what triggers family revocation
3. Row locks instead of counters in SQL — login locks the user row (`FOR UPDATE`) and applies the pure lockout function, so ten parallel guesses count exactly ten; owner updates lock the active owners first so two owners can't demote each other
4. The request trusts the database, not the token — the user's role and `is_active` are read on every request, and the JWT only says who and which refresh family
5. Credential lookups are the one place without `org_id` — the credential reveals the tenant, and the repository scan test allows exactly that module

## Session 2 — CI (2026-10-07)

**PR:** (link after opening)

**Built:**
- `.github/workflows/ci.yml`: lint, types, test, concurrency, migrations, contract, security on PRs into and pushes to dev/uat/release/main; Postgres 17 + Redis services, uv cache, `uv sync --frozen`
- `.github/dependabot.yml`: uv, github-actions, docker; weekly; target `dev`
- One real `@pytest.mark.concurrency` test: 50 concurrent `/health/ready` with a 20-connection pool
- `docs/BRANCHING.md` lists the exact check names to mark required

**Decisions** (plan.md / ADR updated?):
- pytest-xdist deferred; the test job runs plain `pytest` (plan.md updated)
- `types` runs `mypy` with the same scope as `make lint` (plan.md updated)
- contract is a placeholder (starts the app, fetches `/openapi.json`); Schemathesis comes later
- gitleaks runs as the CLI (no action licence needed); Trivy uses `--ignore-unfixed`

**Carried forward / TODO:**
- Replace the contract placeholder with Schemathesis once endpoints exist (needs approval as a dependency, or run via `uvx`)
- Add `release-check` to `release` rules after session 12
- Mark the seven checks required (BRANCHING.md step 2)

**What I should understand:**
1. Job name = status check name — renaming a job silently un-requires it
2. Service containers + health checks — jobs wait for Postgres/Redis before steps run
3. The concurrency job uses `--no-cov` — the coverage gate belongs to `test` only

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
