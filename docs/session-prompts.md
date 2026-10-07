# Session prompts

Open a **new** session on claude.ai/code with the `slotline` repo **on the `dev` branch**,
paste the prompt for that session, and follow the loop in `docs/START-HERE.md` section 4.
Every session works on `feature/sNN-name` branched from `dev` and opens its PR into `dev`
(see `docs/BRANCHING.md`). Promotions to `uat`, `release` and `main` use the promotion
prompts at the bottom.

Every prompt follows the same shape: read context → plan → wait for OK → build → test → PR.
After merging, run the **progress prompt** at the bottom.

---

## Session 0 — check the setup (optional, 10 min, no code)

```text
Read CLAUDE.md, docs/PROJECT-OVERVIEW.md, docs/plan.md, docs/architecture.md,
docs/BRANCHING.md and docs/START-HERE.md. Don't write any code. Tell me:
1. In 5 bullets, what Slotline is and how the API, worker and Postgres fit together.
2. Anything in docs/plan.md that is contradictory, ambiguous or risky.
3. Whether docker, docker compose, uv and python 3.13 are available here (run the version
   commands), and whether you can pull postgres:17.
4. Which branch you're on (it should be dev) and confirm you understand the branch flow.
```

---

## Session 1 — Skeleton

```text
Read CLAUDE.md, docs/plan.md (sections "Architecture and tech stack" and "Repository layout
and conventions") and docs/architecture.md section 2.

Goal: session 1, Skeleton.
Build: uv project (Python 3.13, pyproject.toml, uv.lock), src/slotline layout from the plan,
create_app() with config via pydantic-settings, GET /api/v1/health/live and /health/ready
(ready checks Postgres and Redis), structlog JSON logging, X-Request-ID middleware, a Problem
Details error handler with errors.py, clock.py with an injectable Clock, Makefile (dev, worker
placeholder, test, lint, migrate, seed placeholder), compose.yaml (postgres:17 with btree_gist
enabled, redis:7, mailpit, api, worker), multi-stage Dockerfile with a non-root user,
.env.example, pre-commit (ruff, ruff-format, mypy), Alembic initialised (empty baseline),
pytest configured with a tests/integration conftest that uses the real Postgres container.

Done when: `make dev` serves /docs; `docker build .` works; `make lint` and `make test`
pass with at least the health tests.

First reply with your plan: the file list and the tests you'll add. Wait for my OK.
Then implement on branch feature/s01-skeleton (from dev), run make lint and make test, and open a PR into dev titled
"feat: project skeleton" following the PR rules in CLAUDE.md.
```

---

## Session 2 — CI

```text
Read CLAUDE.md and docs/plan.md section "CI/CD and deployment" (ci.yml table) and
docs/progress.md.

Goal: session 2, CI.
Build: .github/workflows/ci.yml with the seven jobs from the plan (lint, types, test,
concurrency, migrations, contract, security), triggered on pull_request into and push to
dev, uat, release and main. Keep the existing branch-flow.yml. Postgres 17 + Redis service containers,
uv cache, `uv sync --frozen`. The contract job may be a placeholder that starts the app and
fetches /openapi.json; concurrency may run an empty marker for now but must be wired.
Security: pip-audit, gitleaks, Trivy image scan failing on HIGH/CRITICAL.
Also .github/dependabot.yml (pip, github-actions, docker; weekly; target-branch: dev).
Then update the "GitHub settings to click" section of docs/BRANCHING.md with the exact
names of the seven new status checks so I can mark them required.

Done when: all seven jobs pass on the PR. Then push one extra commit with a deliberate lint
error, confirm the lint job fails, and revert it.

Plan first, wait for my OK. Branch feature/s02-ci from dev. PR into dev: "ci: seven-check pipeline and dependabot".
```

---

## Session 3 — Tenancy and auth

```text
Read CLAUDE.md, docs/plan.md (Tables: organizations, users, refresh_tokens, api_keys;
API endpoints /auth/*, /me, /api-keys, /users; Security checklist) and docs/architecture.md
section 3, and docs/progress.md.

Goal: session 3, Tenancy and auth.
Build: models + migration for organizations, users, refresh_tokens, api_keys (UUID v7 ids,
org_id, timestamps). argon2id password hashing. PyJWT 15-min access tokens with a `kid`
header. Rotating 30-day refresh tokens with family_id; reuse of a rotated token revokes the
whole family. Hashed API keys with `sl_live_` prefix, shown once. Endpoints: signup, login,
refresh, logout, /me, /api-keys (owner), /users (owner). deps.current_principal supporting
both Bearer JWT and X-API-Key, producing a Principal(org_id, user_id|key_id, role, scopes).
Login rate limit placeholder hook (real limiter comes in session 7).
Tests: success, validation, wrong password, expired token, refresh reuse revokes family,
owner-only endpoints return 403 for staff, and a tenant-isolation test scaffold that, given
the OpenAPI spec, calls each endpoint as org A with org B's IDs and expects 404.

Done when: token reuse revokes the family; the tenant-isolation scaffold runs in CI.

Plan first, wait for my OK. Branch feature/s03-auth from dev. PR into dev: "feat: tenancy, staff auth and api keys".
```

---

## Session 4 — Catalogue

```text
Read CLAUDE.md, docs/plan.md (Tables: providers, services, provider_services,
availability_rules, time_off, customers; their endpoints) and docs/progress.md.

Goal: session 4, Catalogue.
Build: models, migration, repositories, services and CRUD routes for providers (delete =
deactivate), services (duration_minutes, buffer_minutes, price_paise), provider_services,
PUT /providers/{id}/availability (replaces the whole week atomically, validates no
overlapping rules per weekday), time-off (tstzrange; rejected with 409 if it overlaps
confirmed bookings unless force=true — the bookings table doesn't exist yet, so put the
check behind a repository method that returns empty for now and add a TODO pointing at
session 6), customers (E.164 phone validation, search by phone or name). Cursor pagination
helper used by every list endpoint.
Tests for every endpoint: success, validation, auth, other tenant → 404; availability
replace is atomic.

Done when: weekly hours replace in one call; time-off overlap rule has a test (marked
xfail until session 6 if needed).

Plan first, wait for my OK. Branch feature/s04-catalogue from dev. PR into dev: "feat: providers, services, hours,
time off and customers".
```

---

## Session 5 — Availability

```text
Read CLAUDE.md, docs/plan.md section "Availability, the one hard read" and
docs/architecture.md section 4, and docs/progress.md.

Goal: session 5, Availability.
Build: pure functions in domain/slots.py and domain/timezones.py: expand weekly rules for a
date range in the provider's IANA zone → UTC intervals; subtract intervals; generate starts
at a 15-minute granularity where duration + buffer fits; drop past starts and those inside
minimum notice (default 2 h, from org settings). Then services/availability_service.py and
GET /api/v1/availability?service_id&from&to&provider_id (range capped at 31 days, grouped
by provider, UTC output). Use the injected Clock.
Tests: unit tests + Hypothesis properties (no start overlaps a blocked interval; every start
+ duration + buffer fits inside working hours; output sorted and unique), an Europe/Dublin
DST-change week, buffers, minimum notice, 31-day cap → 422. Integration test for the endpoint.

Done when: property tests pass, including the DST week and buffers.

Plan first, wait for my OK. Branch feature/s05-availability from dev. PR into dev: "feat: computed availability".
```

---

## Session 6 — Bookings core (the big one)

```text
Read CLAUDE.md, docs/plan.md section "Data model and concurrency design" in full (the SQL,
the five rules, booking lifecycle) and docs/architecture.md sections 5 and 6, and
docs/progress.md.

Goal: session 6, Bookings core.
Build: migration with booking_status enum, bookings table exactly as in the plan (during,
blocked, bookings_no_overlap exclusion constraint, CHECKs, indexes), booking_events,
outbox_events. domain/booking_state.py as an allowed-transitions table. Services:
create_hold (expire stale overlapping holds first in the same transaction, insert held row
with hold_expires_at from org settings, map 23P01 → 409 slot_unavailable),
confirm_hold (410 hold_expired if past), direct book. Every transition writes booking_events
+ outbox_events in the same transaction. Endpoints: POST /holds, POST /holds/{id}/confirm,
POST /bookings, GET /bookings (filters, cursor), GET /bookings/{id} with events.
Wire the time-off overlap check from session 4 to real bookings.
Tests: the 200-concurrent-holds test from docs/plan.md "The concurrency proof" (pool size
≥ 20, @pytest.mark.concurrency), back-to-back bookings allowed, buffer blocks the next slot,
expired hold doesn't block, 409/410 behaviour, invalid transitions → 409.

Done when: the 200-concurrent test gives exactly {201: 1, 409: 199} and the DB has one
active booking.

In the PR "Things to understand" section, explain the exclusion constraint and why
SELECT-then-INSERT would fail. Plan first, wait for my OK. Branch feature/s06-bookings-core from dev.
PR into dev: "feat: holds and bookings with exclusion-constraint guarantee".
```

---

## Session 7 — Lifecycle and safety

```text
Read CLAUDE.md, docs/plan.md (Idempotency, Optimistic concurrency, booking endpoints,
Conventions, rate limits) and docs/architecture.md sections 2 and 6, and docs/progress.md.

Goal: session 7, Lifecycle and safety.
Build: reschedule (single UPDATE of during + blocked), cancel with reason, complete,
no-show; If-Match version checks (412) on edits; idempotency middleware with the
idempotency_keys table (in_progress / replay / 422 reused / 409 in progress, 24 h expiry);
Redis sliding-window rate limiter (600/min per API key, 10/min login per IP, headers,
429 with Retry-After); account lockout after 10 failed logins in 15 min.
Tests: the four extra races from docs/plan.md (overlapping ranges, reschedule vs new
booking, same idempotency key ×50, plus a placeholder for the worker race to be completed in
session 8), plus unit/integration tests for each new endpoint.

Done when: the race tests pass.

Plan first, wait for my OK. Branch feature/s07-lifecycle from dev. PR into dev: "feat: reschedule, cancel,
idempotency and rate limits".
```

---

## Session 8 — Worker

```text
Read CLAUDE.md, docs/plan.md section "Background automation" (How the worker works, hold
expiry, housekeeping) and docs/architecture.md section 7, and docs/progress.md.

Goal: session 8, Worker.
Build: jobs table (dedupe_key unique), src/slotline/worker/main.py with: outbox relay
(unpublished events → jobs, set published_at), claim loop using FOR UPDATE SKIP LOCKED
LIMIT 20 with locked_until, exponential backoff with jitter, dead after max_attempts,
LISTEN/NOTIFY wake-up with a 5 s poll fallback, scheduler for periodic jobs with per-period
dedupe keys, graceful SIGTERM shutdown (stop claiming, finish within 25 s). Jobs: hold
expiry every 30 s (writes booking.expired), nightly housekeeping in batches of 1,000.
`make worker` runs it; compose runs it.
Tests: each handler with a frozen Clock, retry + dead-lettering, dedupe, shutdown, and the
race test: 2 workers × 500 jobs → each runs exactly once.

Done when: the 2-worker test passes.

Plan first, wait for my OK. Branch feature/s08-worker from dev. PR into dev: "feat: postgres-backed worker with
outbox".
```

---

## Session 9 — Notifications

```text
Read CLAUDE.md, docs/plan.md ("The automations" table, "Notifications layer") and
docs/progress.md.

Goal: session 9, Notifications.
Build: Notifier protocol (send(message) -> provider_message_id), ConsoleNotifier,
SmtpNotifier (Mailpit), and one email API provider (ask me which: Resend, Postmark or SES)
selected by config. notifications table. Jinja2 templates (text + HTML) for confirmation,
reminder, rescheduled, cancelled, daily digest. Handlers: confirmation on booking.confirmed;
reminders at org-configured offsets (default 24 h and 2 h) scheduled on confirm/reschedule;
reschedule/cancel notices that cancel pending reminders in the same transaction; daily
digest at 19:00 org time.
Tests with a frozen Clock: reminder never sends for a cancelled or rescheduled booking;
digest runs once per org per day; Mailpit receives a real email in an integration test.

Done when: the cancelled-booking reminder test passes.

Plan first, wait for my OK. Branch feature/s09-notifications from dev. PR into dev: "feat: email notifications and
reminders".
```

---

## Session 10 — Waitlist and webhooks

```text
Read CLAUDE.md, docs/plan.md (waitlist_entries, webhook tables and endpoints, "Waitlist
offer" row, "Webhook format", Security checklist SSRF item) and docs/architecture.md
section 8, and docs/progress.md.

Goal: session 10, Waitlist and webhooks.
Build: waitlist endpoints; offer flow on booking.cancelled / booking.expired / time off
removed: earliest matching entry gets a 15-minute hold via the normal hold path + offer
email; unclaimed → expires → next entry. Webhook endpoints CRUD (secret shown once),
delivery job per subscribed endpoint signed as in the plan, retries 1m/5m/30m/2h/12h then
dead, deliveries log + manual retry endpoint. SSRF guard: HTTPS only, reject hosts
resolving to private/loopback/link-local. examples/verify_webhook.py (~20 lines).
Tests: a cancellation produces a signed webhook (verify with the example) and a waitlist
hold; SSRF cases rejected; retry schedule with a frozen Clock.

Done when: one cancellation → signed webhook + waitlist hold, end to end.

Plan first, wait for my OK. Branch feature/s10-waitlist-webhooks from dev. PR into dev: "feat: waitlist offers and
signed webhooks".
```

---

## Session 11 — Observability and hardening

```text
Read CLAUDE.md, docs/plan.md section "Observability, security and operations" and the
Testing strategy table, and docs/architecture.md section 10, and docs/progress.md.

Goal: session 11, Observability and hardening.
Build: OpenTelemetry for FastAPI, SQLAlchemy, httpx, Redis; trace ID stored on outbox
events and continued in the worker. Prometheus metrics from the plan's table on an internal
/metrics. Sentry for both processes (DSN from env, off when unset). Security headers, CORS
closed by default, 1 MB body cap, pagination cap 100, log masking. Turn on the real
Schemathesis contract job. loadtest/locustfile.py with a booking-heavy profile and
`make loadtest`. docs/security.md walking through the OWASP API Top 10.

Done when: contract job is green; p95 for POST /holds < 300 ms at 50 req/s locally (put the
numbers and machine specs in the PR).

Plan first, wait for my OK. Branch feature/s11-observability from dev. PR into dev: "feat: tracing, metrics and
hardening".
```

---

## Session 12 — Ship it

```text
Read CLAUDE.md, docs/plan.md sections "CI/CD and deployment" and "Definition of done",
and docs/progress.md.

Goal: session 12, Ship it. Host: <Fly.io or Render — tell Claude which>.
Build the three workflows in docs/plan.md "Deploy workflows":
- deploy-uat.yml on push to uat: build image once tagged with SHA → GHCR; alembic upgrade
  head as a release command; deploy API ×2 + worker ×1 to UAT using the `uat` GitHub
  Environment; wait for /health/ready; smoke suite.
- release-check.yml on push to release: full suite, load test with p95 in the job summary,
  CHANGELOG.md entry matches the version in pyproject.toml.
- deploy-prod.yml on push to main: reuse the SHA image; manual approval via the `production`
  Environment; migrate, deploy, smoke; GitHub release + tag vX.Y.Z from conventional commits
  (the workflow creates the tag; cloud sessions can't push tags).
Also CHANGELOG.md starting at v0.1.0, host config files, tests/smoke
suite pointed at a BASE_URL. scripts/seed.py (demo clinic: 3 providers, 5 services, 2 weeks
of bookings). docs/runbook.md (one entry per alert + worker stuck, DB at connection limit,
email provider down, roll back a deploy). docs/adr/0001–0004 (exclusion constraint vs
locking, Postgres queue vs broker, holds with expiry, idempotency storage). README rewrite
per "Definition of done" with the results table.
List every secret and click-step I must do myself (host account, DB with btree_gist,
GitHub Environments) in docs/deploy-checklist.md. Never ask me to paste secrets here.

Done when: after this PR is merged, promoting dev → uat deploys UAT and promoting
release → main reaches production after one approval (I'll run the promotions).

Plan first, wait for my OK. Branch feature/s12-ship from dev. PR into dev: "feat: deploy pipeline, runbook and docs".
```

---

## Promotion prompts (run when I decide a milestone is ready; see docs/BRANCHING.md)

**dev → uat:**

```text
Open a PR from dev into uat titled "promote: dev → uat (<sessions>)". In the description list
every PR merged into dev since the last promotion, and a "What to test on UAT" checklist built
from each session's "Done when" line in docs/plan.md. Don't merge it; I will, with a merge commit.
```

**uat → release (with version bump):**

```text
We're cutting release v<X.Y.Z>. Step 1: open a PR from uat into release titled
"release: v<X.Y.Z> candidate", then stop and wait for me to merge it.
Step 2 (after I say it's merged): branch chore/release-v<X.Y.Z> from release, bump the version
in pyproject.toml, add the CHANGELOG.md entry from the conventional commits since the last tag,
and open a PR into release. Don't merge anything.
```

**release → main:**

```text
Open a PR from release into main titled "release: v<X.Y.Z>". In the description: the CHANGELOG
entry, migrations included (and whether each is backwards-compatible), and the rollback plan
(previous image SHA). Don't merge it; I'll merge with a merge commit and approve the deploy.
```

**Hotfix:**

```text
Production bug: <describe>. Branch hotfix/<name> from main, write a failing test that
reproduces it, fix it, and open a PR into main. After I merge it, open three back-merge PRs
from main into release, uat and dev. Don't merge anything.
```

---

## Utility prompts

**Progress (run after every merge, in the same session or a new one):**

```text
Session <N> is merged. Update docs/progress.md: add an entry with date, PR link, what was
built, decisions made (and whether docs/plan.md or an ADR was updated), known gaps or TODOs
carried forward, and a "What I should understand" list of 3–5 concepts from this session with
a one-line explanation each. Open a PR titled "docs: progress after session <N>".
```

**Explain code (anytime):**

```text
Explain <path>:<lines> as if I'll be asked about it in an interview: what it does, why it's
written this way, what would break if it were written the naive way, and one follow-up
question an interviewer might ask.
```

**Session is running long:**

```text
Stop adding features. Make sure what exists passes make lint and make test, open the PR with
what's done, and list exactly what's left so I can start a new session for it.
```

**CI failing and you don't know why:**

```text
CI job <name> is failing on this PR. Read the failing log, explain the root cause in 2–3
sentences, then fix it. Don't disable tests or lower thresholds.
```

**Plan drifted:**

```text
Compare the code on main with docs/plan.md. List every place they disagree. Don't change
anything yet; I'll decide which one is right.
```
