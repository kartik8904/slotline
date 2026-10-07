# Slotline Build Plan

Source: the "Slotline Build Plan" doc (5 Oct 2026), with the branch flow from
`docs/BRANCHING.md` applied (7 Oct 2026; `release` is production, `main` is the stable record). Diagrams live in `docs/architecture.md`.

## Overview

Slotline is a multi-tenant booking API for clinics, salons and similar businesses that can never double-book a provider, plus the background automation a real booking product needs: expiring holds, reminders, waitlist offers and signed webhooks. It's the P1 project of your plan (October to November), and later the system Vaani books into through an MCP server.

**Production-ready means, concretely:**

- Correctness is enforced by the database, not by hope: a Postgres exclusion constraint makes overlapping bookings impossible, and a test proves it under 200 concurrent requests.
- Every write is safe to retry (idempotency keys), every request is traceable (request IDs, structured logs, traces), and every failure returns one consistent error shape.
- Nothing reaches production without passing lint, type checks, tests, a migration check and a security scan in CI, then moving through `dev` → `uat` → `release`. Merges to `uat` deploy to UAT automatically; merges to `release` deploy production after one approval; `main` records each release once it has proved stable.
- Automation runs in a worker process that survives restarts, retries with backoff, and never sends the same reminder twice.
- Someone else can run it from the README in under 10 minutes.

**In scope:** organisations (tenants), staff users, providers, services, weekly working hours, time off, customers, computed availability, holds, bookings (confirm, reschedule, cancel, complete, no-show), waitlist, reminders, outgoing webhooks, API keys, admin audit trail.

**Out of scope for v1:** payments, group classes with capacity above one, recurring bookings, a full web front end (Swagger UI is the interface), SMS and WhatsApp delivery (email first; the notification layer is built so a channel can be added later), and calendar sync. Each is listed as a stretch goal at the end.

**Effort:** about 6 weeks at your 22 hours a week, split into 12 build sessions (see the build plan section).

## Architecture and tech stack

Slotline runs as two processes from one codebase, an API and a worker, sharing one Postgres database; Postgres is also the job queue, so v1 needs no message broker.

Diagram: `docs/architecture.md` section 1.

The API never calls the email provider or webhook receivers directly: it writes an outbox event, and the worker does the slow, retryable work.

| Layer | Choice | Why this one |
| --- | --- | --- |
| Language | Python 3.13 | Your plan's AI track is Python; one language end to end |
| Packaging | uv + pyproject.toml + uv.lock | Fast, reproducible installs; the Build Book template already uses it |
| Web framework | FastAPI + Pydantic v2 | Typed validation, OpenAPI docs for free, async |
| Database | PostgreSQL 17 with the btree_gist extension | Exclusion constraints on time ranges: the double-booking guarantee |
| DB access | SQLAlchemy 2.0 (async) + asyncpg | Explicit transactions and row locks; mature |
| Migrations | Alembic | Versioned schema changes, checked in CI |
| Config | pydantic-settings | App refuses to start if a required variable is missing |
| Auth | JWT access + rotating refresh tokens (PyJWT), argon2 password hashing, hashed API keys | Staff log in; machine clients like Vaani use API keys |
| Rate limiting | Redis (sliding window) | Shared across API instances; the only extra service |
| Jobs and automation | Postgres jobs table + transactional outbox, worker using SELECT … FOR UPDATE SKIP LOCKED | Jobs commit atomically with the booking; safe with many workers; you learn how queues work |
| Email | A transactional email API (Resend, Postmark or Amazon SES) behind a Notifier interface; Mailpit locally | Swap providers without touching business logic |
| Observability | structlog JSON logs, OpenTelemetry traces, Prometheus metrics, Sentry for errors | Every request traceable from log line to trace |
| Testing | pytest, pytest-asyncio, httpx, a real Postgres (CI service container), Hypothesis, Schemathesis | Real Postgres in tests, property-based and contract tests |
| Quality | ruff (lint + format), mypy (strict), pre-commit | Same checks locally and in CI |
| Delivery | Docker multi-stage image, GitHub Actions, GHCR, a container host (Fly.io or Render now, AWS ECS + RDS in July per Brahmastra P9) | Cheap to start, same image moves to AWS later |

Pin exact versions in uv.lock on day one and let Dependabot propose upgrades; check that your chosen managed Postgres allows the btree_gist extension before you pick it.

## Data model and concurrency design

A Postgres exclusion constraint on each booking's time range makes two active bookings for the same provider overlap impossible, whatever the application code does. Slots are never stored: availability is computed from working hours minus time off minus active bookings.

### Tables

Every business table carries `org_id` (the tenant), `id` (UUID v7, sortable), `created_at` and `updated_at`. All timestamps are `timestamptz` in UTC; each organisation and provider stores an IANA time zone (default `Asia/Kolkata`) used only for display and for expanding working hours.

| Table | Purpose | Key columns |
| --- | --- | --- |
| organizations | A tenant: one clinic or salon | name, slug, timezone, settings jsonb (hold minutes, reminder offsets) |
| users | Staff who log in | email (unique per org), password_hash, role (owner, staff), is_active |
| refresh_tokens | Rotating refresh tokens | user_id, token_hash, family_id, expires_at, revoked_at |
| api_keys | Machine clients such as Vaani | name, prefix, key_hash, scopes, last_used_at, revoked_at |
| providers | A person or room that can be booked | name, timezone, is_active |
| services | What can be booked | name, duration_minutes, buffer_minutes, price_paise (display only) |
| provider_services | Which provider offers which service | provider_id, service_id |
| availability_rules | Weekly working hours | provider_id, weekday (0–6), start_time, end_time, effective_from, effective_to |
| time_off | Leave, holidays, breaks | provider_id, during tstzrange, reason |
| customers | People who book | name, phone (E.164), email, notes, consent flags |
| bookings | Holds and bookings | provider_id, service_id, customer_id, status, during, blocked, hold_expires_at, source (api, staff, waitlist, voice), version |
| booking_events | Append-only history | booking_id, type, actor, from_status, to_status, data jsonb |
| waitlist_entries | Wanted a time that was full | service_id, provider_id (optional), customer_id, window tstzrange, status, position |
| idempotency_keys | Safe retries | key, request_hash, status, response_code, response_body, expires_at |
| outbox_events | Events written in the same transaction as the change | type, aggregate_id, payload, published_at |
| jobs | The work queue | kind, payload, run_at, attempts, max_attempts, locked_by, locked_until, last_error, status, dedupe_key |
| notifications | One row per message to send | booking_id, channel, template, send_at, status, provider_message_id |
| webhook_endpoints | Where to send events | url, secret, event_types, is_active |
| webhook_deliveries | Every delivery attempt | endpoint_id, event_id, attempt, status_code, next_attempt_at, status |

### The double-booking guarantee

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TYPE booking_status AS ENUM
  ('held', 'confirmed', 'completed', 'cancelled', 'no_show', 'expired');

CREATE TABLE bookings (
  id              uuid PRIMARY KEY,
  org_id          uuid NOT NULL REFERENCES organizations(id),
  provider_id     uuid NOT NULL REFERENCES providers(id),
  service_id      uuid NOT NULL REFERENCES services(id),
  customer_id     uuid NOT NULL REFERENCES customers(id),
  status          booking_status NOT NULL,
  during          tstzrange NOT NULL,          -- what the customer sees, half-open [start, end)
  blocked         tstzrange NOT NULL,          -- during + the service's buffer time
  hold_expires_at timestamptz,
  source          text NOT NULL DEFAULT 'api',
  version         integer NOT NULL DEFAULT 1,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (lower(during) < upper(during)),
  CHECK (status <> 'held' OR hold_expires_at IS NOT NULL),
  CONSTRAINT bookings_no_overlap EXCLUDE USING gist (
    provider_id WITH =,
    blocked     WITH &&
  ) WHERE (status IN ('held', 'confirmed'))
);

CREATE INDEX ON bookings (org_id, provider_id, lower(during));
CREATE INDEX ON bookings (hold_expires_at) WHERE status = 'held';
```

Five rules make it hold up in production:

1. **Half-open ranges.** `[10:00, 10:30)` and `[10:30, 11:00)` don't overlap, so back-to-back bookings work.
2. **Buffers live in `blocked`.** A 30-minute service with a 10-minute clean-up blocks 40 minutes, while the customer still sees 30.
3. **Stale holds don't block.** Inside the booking transaction, first run `UPDATE bookings SET status = 'expired' WHERE provider_id = :p AND status = 'held' AND hold_expires_at < now() AND blocked && :range`. A hold that expired a second ago never blocks a new booking while it waits for the worker.
4. **Translate the violation.** Catch SQLSTATE `23P01` (exclusion violation) and return `409 slot_unavailable`. Never check availability with a SELECT first and then insert: two requests can both see the slot free. The constraint is the only check that counts.
5. **Reschedule in one statement.** Update `during` and `blocked` on the same row in one transaction; the constraint compares against every other active booking, so a failed reschedule leaves the original booking untouched.

### Idempotency

Every `POST` that creates or changes a booking requires an `Idempotency-Key` header. The middleware inserts `(org_id, key, request_hash, status='in_progress')` with `ON CONFLICT DO NOTHING`. If the key already exists with the same request hash and a stored response, it replays that response; with a different hash it returns `422 idempotency_key_reused`; while still in progress it returns `409 request_in_progress`. Keys expire after 24 hours.

### Optimistic concurrency for edits

Staff edits to a booking's notes or customer send `If-Match: <version>`. A mismatch returns `412 precondition_failed`, so two staff members can't silently overwrite each other.

### Booking lifecycle

Diagram: `docs/architecture.md` section 6 (2 active states, 4 final).

The state machine lives in `domain/booking_state.py` as a table of allowed transitions; any other transition returns `409 invalid_transition`, and every transition writes a `booking_events` row.

## API specification

All routes live under `/api/v1`, take and return JSON, and authenticate with either `Authorization: Bearer <JWT>` (staff) or `X-API-Key: <key>` (machine clients). The organisation always comes from the credential, never from the URL, so one tenant can't name another tenant's IDs.

### Endpoints

| Method and path | Who | What it does |
| --- | --- | --- |
| POST /auth/signup | Public | Creates an organisation and its owner user |
| POST /auth/login | Public | Returns a 15-minute access token and a 30-day refresh token |
| POST /auth/refresh | Public | Rotates the refresh token; reuse of an old one revokes the whole family |
| POST /auth/logout | Staff | Revokes the current refresh token |
| GET /me | Any | Current user or key, organisation and scopes |
| POST, GET, DELETE /api-keys | Owner | Create (key shown once), list, revoke |
| POST, GET, PATCH, DELETE /users | Owner | Invite and manage staff |
| POST, GET, PATCH, DELETE /providers | Staff | Manage providers (delete = deactivate) |
| PUT /providers/{id}/availability | Staff | Replace the weekly working hours in one call |
| POST, GET, DELETE /providers/{id}/time-off | Staff | Leave and breaks; rejected if it overlaps confirmed bookings unless `force=true` |
| POST, GET, PATCH, DELETE /services | Staff | Manage services, durations and buffers |
| POST, GET, PATCH /customers | Staff, key | Create, search by phone or name, update |
| GET /availability | Staff, key | Open start times for a service between two dates, optionally for one provider |
| POST /holds | Staff, key | Holds a slot for 5 minutes (configurable); returns `hold_expires_at` |
| POST /holds/{id}/confirm | Staff, key | Turns a hold into a confirmed booking; `410 hold_expired` if too late |
| POST /bookings | Staff, key | Hold and confirm in one step |
| GET /bookings | Staff, key | List with filters (provider, customer, status, date range), cursor pagination |
| GET /bookings/{id} | Staff, key | One booking with its event history |
| POST /bookings/{id}/reschedule | Staff, key | Moves to a new start time atomically |
| POST /bookings/{id}/cancel | Staff, key | Cancels with a reason; frees the slot and triggers the waitlist |
| POST /bookings/{id}/complete | Staff | Marks attended |
| POST /bookings/{id}/no-show | Staff | Marks missed |
| POST, GET, DELETE /waitlist | Staff, key | Join, list, leave the waitlist |
| POST, GET, DELETE /webhooks | Owner | Manage endpoints; the signing secret is shown once |
| GET /webhooks/{id}/deliveries | Owner | Delivery log with status codes |
| POST /webhooks/{id}/deliveries/{did}/retry | Owner | Re-sends one delivery |
| GET /health/live, /health/ready | Public | Liveness; readiness checks Postgres and Redis |
| GET /metrics | Internal | Prometheus metrics, not exposed publicly |

### Availability, the one hard read

`GET /availability?service_id=…&from=2026-11-03&to=2026-11-09&provider_id=…` returns start times grouped by provider. The algorithm, done in SQL plus Python:

1. Expand each provider's weekly rules into concrete intervals for the date range, in the provider's time zone, then convert to UTC.
2. Subtract time off and the `blocked` range of every held or confirmed booking (expired holds ignored).
3. Walk each free interval in steps of the slot granularity (default 15 minutes) and keep starts where duration + buffer fits.
4. Drop starts in the past or closer than the minimum notice (default 2 hours).

Cap the range at 31 days. Availability is a hint, not a promise: only the hold or booking call guarantees the slot.

### Example: holding a slot

```http
POST /api/v1/holds
X-API-Key: sl_live_3kP…
Idempotency-Key: 6f1c2a9e-0b7d-4f6e-9a1d-2f3c4b5a6d7e
Content-Type: application/json

{"service_id": "0192…", "provider_id": "0192…", "customer_id": "0192…",
 "start": "2026-11-04T10:30:00+05:30"}
```

```http
HTTP/1.1 201 Created
Location: /api/v1/bookings/0193…

{"id": "0193…", "status": "held", "start": "2026-11-04T05:00:00Z",
 "end": "2026-11-04T05:30:00Z", "hold_expires_at": "2026-11-03T09:12:00Z", "version": 1}
```

### Errors

Every error uses one shape, Problem Details (RFC 9457) with a stable `code` field clients can switch on:

```json
{"type": "https://slotline.dev/errors/slot_unavailable", "title": "Slot unavailable",
 "status": 409, "code": "slot_unavailable", "detail": "Dr Mehta is booked 10:30–11:00 on 4 Nov.",
 "request_id": "req_01JB…"}
```

| Status | code | When |
| --- | --- | --- |
| 400 | invalid_request | Malformed JSON or headers |
| 401 | unauthenticated | Missing, expired or invalid token or key |
| 403 | forbidden | Valid credential, wrong role or scope |
| 404 | not_found | Unknown ID or another tenant's ID (never 403, to avoid leaking existence) |
| 409 | slot_unavailable | Exclusion constraint fired |
| 409 | invalid_transition | e.g. confirming a cancelled booking |
| 409 | request_in_progress | Same idempotency key still running |
| 410 | hold_expired | Confirming after the hold ran out |
| 412 | precondition_failed | `If-Match` version mismatch |
| 422 | validation_error | Field errors, listed per field |
| 422 | idempotency_key_reused | Same key, different body |
| 429 | rate_limited | With `Retry-After` |
| 500 | internal_error | Logged with the request ID; no internals in the body |

### Conventions

- Cursor pagination: `?limit=50&cursor=…`, response has `next_cursor`. Never offset.
- Times in requests may carry any offset; responses are always UTC with `Z`.
- Every response carries `X-Request-ID`; send one in and it's kept.
- Rate limits: 600 requests a minute per API key, 10 login attempts a minute per IP. Headers report what's left.

## Background automation

Every automated action starts as a row written in the same transaction as the booking change, so a crash can delay an action but never lose it or run it for a booking that was rolled back.

### How the worker works

- **Outbox.** A booking change inserts an `outbox_events` row (`booking.confirmed`, `booking.cancelled`, …) in the same transaction. The worker turns each unpublished event into jobs and webhook deliveries, then sets `published_at`.
- **Jobs table.** The worker claims due jobs with `SELECT … FROM jobs WHERE status = 'queued' AND run_at <= now() ORDER BY run_at FOR UPDATE SKIP LOCKED LIMIT 20`, sets `locked_until = now() + 2 minutes`, runs them, and marks each `done`, or `queued` again with `run_at` pushed back by exponential backoff with jitter. After `max_attempts` a job becomes `dead` and raises an alert.
- **Many workers are safe.** `SKIP LOCKED` means two workers never take the same job; a crashed worker's lock simply times out and another picks the job up.
- **No duplicates.** Jobs carry a `dedupe_key` with a unique index (for example `reminder:<booking_id>:24h`), and every handler is idempotent: it re-reads the booking and does nothing if the booking changed.
- **Periodic tasks.** A scheduler loop in the same process enqueues recurring jobs (with dedupe keys per period, so two workers don't double-schedule). It uses `LISTEN/NOTIFY` to wake instantly on new outbox rows, with a 5-second poll as backup.
- **Shutdown.** On SIGTERM the worker stops claiming, finishes in-flight jobs within 25 seconds, then exits, so deploys never cut a job in half.

### The automations

| Automation | Trigger | What it does | Guard against mistakes |
| --- | --- | --- | --- |
| Hold expiry | Every 30 seconds | Marks holds past `hold_expires_at` as expired, writes a `booking.expired` event | Rule 3 in the data model means an expired hold never blocks anyone even before this runs |
| Confirmation message | `booking.confirmed` | Emails the customer the time, provider, address and a cancel link | Dedupe key per booking and version |
| Reminders | `booking.confirmed` or rescheduled | Schedules notifications at 24 hours and 2 hours before the start (offsets set per organisation) | Handler skips if the booking is no longer confirmed or its time changed |
| Reschedule and cancel notices | `booking.rescheduled`, `booking.cancelled` | Notifies the customer; cancels pending reminders for the old time | Old reminders marked cancelled in the same transaction |
| Waitlist offer | `booking.cancelled` or `booking.expired`, or time off removed | Finds the earliest waitlist entry whose service, provider and time window fit the freed slot, places a 15-minute hold for them and sends an offer; if unclaimed, the hold expires and the next person is offered | Offer uses the normal hold path, so the exclusion constraint still guards it |
| Auto no-show | 30 minutes after a booking's end, if not marked | Flags the booking for staff review (doesn't change status on its own) | Staff stay in control of outcomes |
| Webhook delivery | Every outbox event | POSTs the event to each subscribed endpoint, signed with HMAC-SHA256 | Retries at 1 min, 5 min, 30 min, 2 h, 12 h, then dead; receivers dedupe on the event ID |
| Daily schedule digest | 19:00 in each organisation's time zone | Emails each provider tomorrow's bookings | Dedupe key per organisation and date |
| Housekeeping | Nightly | Deletes idempotency keys older than 24 h, webhook deliveries older than 30 days, done jobs older than 7 days | Batched deletes of 1,000 rows to avoid long locks |

### Webhook format

```http
POST https://customer.example/hooks/slotline
Content-Type: application/json
Slotline-Event-Id: evt_0193…
Slotline-Timestamp: 1793350800
Slotline-Signature: v1=5f2b…   # HMAC-SHA256(secret, timestamp + "." + body)

{"id": "evt_0193…", "type": "booking.cancelled", "created_at": "2026-11-03T09:00:00Z",
 "data": {"booking": {"id": "0193…", "status": "cancelled", …}}}
```

Receivers should reject timestamps older than 5 minutes. Document this with a 20-line verification snippet in the README; Vaani and AgentGuard will use these events later.

### Notifications layer

A `Notifier` protocol with one method, `send(message) -> provider_message_id`. Implementations: `ConsoleNotifier` (tests), `SmtpNotifier` (Mailpit locally), and one email API provider in production. Templates are Jinja2 files with a plain-text and HTML version each, rendered in the customer's language (English first; Hindi templates are an easy later win for Vaani).

## Repository layout and conventions

One repository, `slotline`, with the route → service → repository layering from your Build Book: routes handle HTTP, services hold business rules and transactions, repositories hold SQL.

```text
slotline/
├── CLAUDE.md                  # how Claude should work in this repo
├── README.md                  # run in 10 minutes, architecture, decisions, results
├── pyproject.toml / uv.lock   # dependencies + ruff, mypy, pytest config
├── Makefile                   # make dev | worker | test | lint | migrate | seed | loadtest
├── Dockerfile                 # multi-stage: uv build → slim runtime, non-root user
├── compose.yaml               # postgres, redis, mailpit, api, worker
├── .env.example               # every variable, documented, no secrets
├── .claude/settings.json      # SessionStart hook for cloud sessions
├── .github/
│   ├── workflows/branch-flow.yml  # enforces feature → dev → uat → release → main
│   ├── workflows/ci.yml       # every PR into dev/uat/release/main and every push to them
│   ├── workflows/deploy-uat.yml   # push to uat → UAT environment (session 12)
│   ├── workflows/release-check.yml # PR into release → full suite + load test + version gate (session 12)
│   ├── workflows/deploy-prod.yml  # push to release → approval → production + tag (session 12)
│   ├── pull_request_template.md
│   └── dependabot.yml
├── alembic/versions/          # one migration per change, never edited after merge
├── docs/
│   ├── PROJECT-OVERVIEW.md · plan.md · architecture.md · BRANCHING.md
│   ├── START-HERE.md · LOCAL-SETUP.md · session-prompts.md · progress.md
│   ├── adr/                   # 0001-exclusion-constraint.md, 0002-postgres-queue.md, …
│   └── runbook.md             # what to do when an alert fires
├── scripts/                   # session-start.sh, seed.py
├── src/slotline/
│   ├── main.py                # create_app(): middleware, routers, exception handlers
│   ├── config.py              # pydantic-settings Settings
│   ├── db.py                  # engine, session factory, transaction helper
│   ├── clock.py               # injectable Clock
│   ├── api/v1/                # auth.py, providers.py, services.py, availability.py, bookings.py, …
│   ├── api/deps.py            # current principal, org scoping, pagination
│   ├── schemas/               # Pydantic request and response models
│   ├── services/              # booking_service.py, availability_service.py, waitlist_service.py, …
│   ├── repositories/          # SQL per aggregate; every query filtered by org_id
│   ├── models/                # SQLAlchemy tables
│   ├── domain/                # pure logic: state machine, slot maths, time zones (no I/O)
│   ├── middleware/            # request_id, logging, idempotency, rate_limit
│   ├── errors.py              # error codes → Problem Details
│   ├── notifications/         # Notifier protocol, providers, templates/
│   ├── webhooks/              # signing, delivery
│   └── worker/                # main.py (loop + scheduler), jobs/ (one handler per kind)
├── tests/
│   ├── unit/                  # domain/: fast, no database
│   ├── integration/           # API + real Postgres
│   ├── concurrency/           # the 200-request proof and race tests
│   ├── contract/              # Schemathesis against the OpenAPI spec
│   └── smoke/                 # run against a deployed URL
├── examples/verify_webhook.py
└── loadtest/locustfile.py     # booking-heavy load profile
```

**Conventions to put in CLAUDE.md and enforce in CI:**

- `domain/` imports nothing from FastAPI or SQLAlchemy, so the hardest logic is unit-tested in milliseconds.
- Services own transactions (`async with uow:`); routes never call `commit`.
- Every repository method takes `org_id` as its first argument. A test scans the repositories for queries without it.
- No `datetime.now()` in business code: inject a `Clock`, so tests can freeze time.
- Conventional commits (`feat:`, `fix:`, `test:`), one pull request per feature into `dev`, squash-merged, each with tests. Promotions between `dev`, `uat`, `release` and `main` use merge commits (see `docs/BRANCHING.md`).
- Every design choice with a trade-off gets a one-page ADR in `docs/adr/`. These become your interview answers.

## Testing strategy

Tests run against a real Postgres, never SQLite or mocks, because the guarantee you're proving lives in Postgres. CI fails below 85% line coverage, and `services/` and `domain/` must reach 95%.

| Layer | What it covers | Tools | Runs |
| --- | --- | --- | --- |
| Unit | State machine transitions, slot generation, time zones (including an Ireland DST week), buffers, minimum notice, signature maths | pytest, Hypothesis | Every PR and push, under 5 s |
| Integration | Every endpoint: happy path, validation, auth, tenant isolation, idempotency replay, error codes | pytest + httpx AsyncClient + Postgres | Every PR and push |
| Concurrency | The double-booking proof and other races | asyncio + separate connections | Every PR and push |
| Worker | Each job handler, retries, dead-lettering, dedupe, shutdown | pytest with a frozen Clock | Every PR and push |
| Contract | The API never returns something its OpenAPI spec doesn't allow, and never 500s on fuzzed input | Schemathesis | Every PR |
| Migrations | `upgrade head`, `downgrade -1`, `upgrade head` again; autogenerate finds no drift | Alembic | Every PR |
| Load | p95 latency for availability and holds at 50 requests per second | Locust | Every PR into `release`, results in README |
| Smoke | Health, login, one hold and confirm against the deployed URL | A short pytest suite pointed at a URL | After every UAT and production deploy |

### The concurrency proof

This is the test you put in the README and talk through in interviews.

```python
@pytest.mark.concurrency
async def test_200_concurrent_holds_for_one_slot_yield_exactly_one(client_factory, seeded_slot):
    clients = [client_factory() for _ in range(200)]           # 200 independent HTTP clients
    async def attempt(i):
        return await clients[i].post("/api/v1/holds", json=seeded_slot.body(customer=i),
                                     headers={"Idempotency-Key": str(uuid4())})
    responses = await asyncio.gather(*(attempt(i) for i in range(200)))

    codes = Counter(r.status_code for r in responses)
    assert codes == {201: 1, 409: 199}                         # no 500s, no second winner
    assert await count_active_bookings(seeded_slot) == 1      # and the database agrees
```

Run it against a database pool of at least 20 connections so requests really overlap. Add four more races the same way:

1. **Overlapping, not identical:** 100 requests for 10:00–10:30 and 100 for 10:15–10:45 → exactly one wins overall.
2. **Reschedule versus new booking** into the same slot → exactly one wins; the loser's booking is unchanged.
3. **Same idempotency key sent 50 times at once** → one booking created; 49 replays or `409 request_in_progress`, never two bookings.
4. **Two workers, 500 jobs** → every job runs exactly once.

### Tenant isolation

A parametrised test creates two organisations and calls every endpoint as org A with org B's IDs; every call must return 404. Generate the endpoint list from the OpenAPI spec, so a new route can't skip the check.

## CI/CD and deployment

Every change reaches production through three pull requests: feature → `dev` → `uat` → `release` (rules in `docs/BRANCHING.md`). **`release` is production**: merging into it deploys after one approval click. `main` is the stable record, updated by a fourth PR from `release` once that version has run cleanly in production. Every PR must pass the branch-flow check and seven CI checks; merging to `uat` deploys to UAT automatically; PRs into `release` must also pass `release-check`.

Diagram: `docs/architecture.md` section 9.

The image is built once per commit, so what passed UAT is byte for byte what reaches production.

### Branches and environments

| Branch | On pull request into it | On push (merge) to it |
| --- | --- | --- |
| `dev` | branch-flow + 7 CI checks | 7 CI checks |
| `uat` | branch-flow + 7 CI checks | CI, build image, migrate + deploy **UAT**, smoke tests |
| `release` | branch-flow + 7 CI checks + **release-check** (full suite, load test, version and CHANGELOG) | Approval → migrate + deploy **production** (same image SHA) → smoke → GitHub release + tag |
| `main` | branch-flow + 7 CI checks | CI only; marks the release as stable |

### ci.yml: on every pull request into, and every push to, dev, uat, release and main

| Job | Steps | Fails the build when |
| --- | --- | --- |
| lint | `uv sync --frozen`, `ruff check`, `ruff format --check` | Any lint or format issue |
| types | `mypy --strict src/` | Any type error |
| test | Postgres 17 + Redis service containers, `alembic upgrade head`, `pytest -n auto --cov` | A failing test or coverage under 85% |
| concurrency | Same services, `pytest -m concurrency` with a 20-connection pool | Any race test fails |
| migrations | upgrade → downgrade -1 → upgrade; `alembic check` for model drift | A migration can't round-trip, or models and migrations disagree |
| contract | Start the app, run Schemathesis against `/openapi.json` | Any 500 or schema violation |
| security | `pip-audit`, `gitleaks` for secrets, build the image and scan it with Trivy | A known high or critical vulnerability, or a committed secret |

Protect `dev`, `uat`, `release` and `main`: require a pull request, the branch-flow check and all seven CI checks; block force pushes and deletions. Cache the uv download directory between runs to keep CI under 5 minutes.

### Deploy workflows

**deploy-uat.yml (push to `uat`):**

1. Build the Docker image once, tag it with the commit SHA, push it to GitHub Container Registry.
2. Run `alembic upgrade head` against UAT as a one-off release command, before the new app version starts.
3. Deploy the API (2 instances) and the worker (1 instance) to UAT; wait for `/health/ready`.
4. Run the smoke suite against the UAT URL.

**release-check.yml (pull request into `release`):** full test suite, the load test against a local stack with p95 posted as a job summary, and a check that `CHANGELOG.md` has an entry for the version in `pyproject.toml` and that no tag for that version exists yet. It runs before the merge because the merge ships to production.

**deploy-prod.yml (push to `release`, or run manually with a SHA for rollback):**

1. Reuse the image already built for that commit (build it if missing).
2. Wait for manual approval (a GitHub Environment named `production` with you as the required reviewer and `release` as its only deployment branch).
3. Run `alembic upgrade head` against production, deploy API and worker, wait for `/health/ready`, run the smoke suite.
4. Create a GitHub release and tag `vX.Y.Z` with notes generated from the conventional commits. Tags are created here because cloud sessions can't push tags.

**Rollback:** run deploy-prod manually with the previous release's SHA to redeploy its image, then fix forward with a `hotfix/*` branch into `release`. `main` shows the last version known to be stable. This only works if migrations are backwards-compatible, so follow expand-then-contract: add a column in one release, start using it in the next, drop the old one in a third. Never rename a column in a single step.

**Hosting now:** Fly.io or Render with a managed Postgres that supports btree_gist and a small managed Redis. Keep costs near zero with one small instance per process on UAT. **Hosting in July (Brahmastra P9):** the same image on AWS ECS Fargate with RDS Postgres, ElastiCache Redis, Secrets Manager and CloudWatch alarms, defined in Terraform.

**Secrets** live in the host's secret store and GitHub Environments (`uat`, `production`), never in the repo. `.env.example` lists every variable with a comment. Rotate the JWT signing key with a key ID (`kid`) so old tokens stay valid during the switch.

**Other automation:** Dependabot weekly for Python packages, GitHub Actions and the Docker base image, targeting `dev`; a nightly scheduled workflow runs the full suite plus the load test against UAT and posts the p95 numbers as a job summary.

## Observability, security and operations

You should be able to answer "is it working, and if not, where?" in under two minutes from a dashboard, and every alert should point to a runbook entry.

### Observability

- **Logs:** structlog, one JSON line per event, always with `request_id`, `org_id`, `route`, `status`, `duration_ms`, and `job_id` in the worker. Never log tokens, API keys, phone numbers or emails in full (mask to the last 4 characters).
- **Traces:** OpenTelemetry auto-instrumentation for FastAPI, SQLAlchemy, httpx and Redis; the worker continues the trace ID stored on each outbox event, so one trace follows a booking from API call to reminder email. Export over OTLP to any backend (Grafana Cloud, Honeycomb or Jaeger locally).
- **Errors:** Sentry for both processes, tagged with release SHA and environment.

| Metric (Prometheus) | Alert when |
| --- | --- |
| `http_requests_total` by route and status | 5xx above 1% for 5 minutes |
| `http_request_duration_seconds` | p95 of POST /holds above 300 ms for 10 minutes |
| `bookings_conflicts_total` | Informational: shows demand and racing clients |
| `jobs_queue_depth`, `jobs_oldest_age_seconds` | Oldest due job older than 5 minutes (the worker is down or stuck) |
| `jobs_dead_total` | Any increase |
| `webhook_deliveries_failed_total` by endpoint | Above 20 failures an hour for one endpoint |
| `notifications_sent_total` by status | Failure rate above 5% |
| `db_pool_in_use` | Above 80% of the pool for 10 minutes |

### Security checklist

- [ ] Passwords hashed with argon2id; API keys stored as SHA-256 hashes, shown once, with a visible prefix (`sl_live_`) so leaked keys are easy to spot
- [ ] Access tokens expire in 15 minutes; refresh tokens rotate and a reused token revokes its whole family
- [ ] Every query scoped by `org_id` (enforced by the repository test); Postgres row-level security as a second layer is a stretch goal
- [ ] Rate limits on login, signup and all writes; account lockout after 10 failed logins in 15 minutes
- [ ] CORS closed by default; security headers (HSTS, no-sniff, frame-deny) on every response
- [ ] Webhook URLs must be HTTPS and must not resolve to private, loopback or link-local addresses (blocks server-side request forgery)
- [ ] Request bodies capped at 1 MB; pagination limit capped at 100
- [ ] Container runs as a non-root user on a slim base image, scanned in CI
- [ ] OWASP API Security Top 10 walked through once, with notes in `docs/security.md`
- [ ] Customer data: export and delete endpoints per customer (GDPR and India's DPDP Act both expect this), and a documented retention period

### Operations

- **Backups:** daily automated backups with 7-day point-in-time recovery from the managed Postgres; restore into a scratch database once and write down how long it took.
- **Runbook** (`docs/runbook.md`): one entry per alert above, saying what it means, how to check, and how to fix it. Include "worker stuck", "database at connection limit", "email provider down", "roll back a deploy" and "ship a hotfix".
- **Status:** a free uptime monitor hitting `/health/ready` every minute, alerting your email or Telegram.
- **Data retention:** cancelled and completed bookings kept 2 years, then customer fields anonymised by a scheduled job.

## Build plan with Claude cloud sessions

Build Slotline in 12 cloud sessions, one pull request into `dev` each, about two sessions a week. You write the plan and the tests' intent, Claude writes most of the code, and you merge only what you can explain line by line (your own Brahmastra rule). Promote `dev` → `uat` → `release` (production) at the milestones in `docs/BRANCHING.md`, then `release` → `main` once each release is stable.

### One-time setup (about 1 hour)

Full steps: `docs/START-HERE.md` (cloud) and `docs/LOCAL-SETUP.md` (your Mac).

1. Create branches `dev`, `uat` and `release` from `main`; set `dev` as the default branch; add the branch rules from `docs/BRANCHING.md`.
2. Install the Claude GitHub App on the repository and connect GitHub at claude.ai/code.
3. Use a cloud environment with **Trusted** network access: it reaches PyPI and Docker Hub. Cloud sessions come with Python, uv, Docker and Docker Compose; PostgreSQL 16 and Redis are installed but not running, so the project uses the postgres:17 container to match CI and production.
4. Add a setup script that pre-pulls your images so they're cached for every session: `docker pull postgres:17 && docker pull redis:7 && docker pull axllent/mailpit`. A setup script that finishes in under about five minutes gets cached.
5. The repo's `.claude/settings.json` SessionStart hook runs `scripts/session-start.sh`, which runs `uv sync` and `docker compose up -d postgres redis mailpit` in cloud sessions once those files exist.
6. Turn on **Auto-fix** for each pull request, so Claude reacts to failing CI checks and your review comments.

### How to run each session

Start each session from `dev` with the prompt for that session in `docs/session-prompts.md`, then review the diff, ask Claude to explain anything unclear, and squash-merge into `dev` only after CI is green. Every prompt has this shape:

```text
Read CLAUDE.md and docs/plan.md, section "<section>".
Goal: <the session goal from the table>.
First write a short plan and the list of tests you'll add. Wait for my OK.
Then implement on feature/sNN-name branched from dev, run make lint and make test, and open
a PR into dev titled "<conventional commit title>" with the test output in the description.
```

The "wait for my OK" step is where you learn: check the plan against this document before any code is written.

### The 12 sessions

| # | Session goal | Claude builds | Done when |
| --- | --- | --- | --- |
| 1 | Skeleton | uv project, create_app(), config, /health routes, structlog, request IDs, Problem Details handler, Makefile, compose.yaml, Dockerfile, pre-commit | `make dev` serves /docs; `docker build` works; one test passes |
| 2 | CI | ci.yml with all seven jobs for PRs and pushes on dev/uat/release/main (contract job can be a placeholder), Dependabot targeting dev | A deliberately failing PR into dev is blocked |
| 3 | Tenancy and auth | organizations, users, refresh tokens, API keys; signup, login, refresh with rotation, logout, /me; argon2; tenant-scoped deps | Token reuse revokes the family; tenant-isolation test scaffold runs |
| 4 | Catalogue | providers, services, provider_services, availability_rules, time_off, customers with CRUD | Weekly hours replace in one call; time off can't overlap confirmed bookings |
| 5 | Availability | domain slot maths (pure functions, Hypothesis tests), the availability endpoint | Property tests pass, including an Ireland DST week and buffers |
| 6 | Bookings core | bookings table with the exclusion constraint, holds, confirm, direct book, the state machine, booking_events | **The 200-concurrent test passes**; 409 and 410 behave as specified |
| 7 | Lifecycle and safety | reschedule, cancel, complete, no-show, If-Match versions, idempotency middleware, rate limiting | The four extra race tests pass |
| 8 | Worker | jobs table, outbox, worker loop with SKIP LOCKED, scheduler, hold expiry, graceful shutdown | 2 workers × 500 jobs: each runs exactly once |
| 9 | Notifications | Notifier protocol, Mailpit + one provider, templates, confirmations, reminders, cancel and reschedule notices, daily digest | Reminders never send for a cancelled booking (test with a frozen clock) |
| 10 | Waitlist and webhooks | waitlist endpoints and offer flow, webhook endpoints, signing, deliveries with retries, SSRF guard | A cancellation produces a signed webhook and a waitlist hold |
| 11 | Observability and hardening | OpenTelemetry, Prometheus metrics, Sentry, security headers, Schemathesis job switched on, load test | Contract job green; p95 for holds under 300 ms at 50 requests a second locally |
| 12 | Ship it | deploy-uat.yml, release-check.yml, deploy-prod.yml, UAT and production on the host, smoke tests, seed demo data, runbook, ADRs, README with results | A change goes dev → uat (deployed to UAT) → release (deployed to production after one approval) → main |

Keep DSA, the Claude track and your job running alongside; if a week slips, cut session 11's polish before cutting tests.

## Definition of done and portfolio write-up

Slotline is done when a stranger can run it, a reviewer can verify its claims from the README, and you can defend every design choice in an interview.

- [ ] Live production URL with Swagger docs and seeded demo clinic data
- [ ] README first screen: what it is, the architecture diagram, and the results table below
- [ ] Concurrency proof test output pasted into the README
- [ ] CI green on all four protected branches; UAT deploys on merge to `uat`; production deploys on merge to `release` after approval
- [ ] `v1.0.0` tagged and released from `release`, then recorded on `main` as stable
- [ ] Worker running in production; a real reminder email received for a test booking
- [ ] Signed webhook verified by a 20-line receiver script in `examples/`
- [ ] Load-test numbers and the machine they ran on
- [ ] At least 4 ADRs: exclusion constraint vs locking, Postgres queue vs a broker, holds with expiry, idempotency storage
- [ ] Runbook with one entry per alert; one backup restore done and timed
- [ ] One build-in-public post on the concurrency test (your November career milestone)

**Results table to fill in for the README:**

| Claim | How it's measured | Result |
| --- | --- | --- |
| No double bookings | 200 concurrent holds on one slot | |
| Safe retries | 50 identical requests with one idempotency key | |
| Hold latency | p95 at 50 requests a second | |
| Availability latency | p95 for a 7-day, 3-provider query | |
| Automation reliability | 2 workers, 500 jobs, each run exactly once | |
| Test coverage | pytest-cov on release | |

**Stretch goals, in order of value for Vaani and your profile:** an MCP server exposing find_slots, hold, confirm, reschedule and cancel (it becomes P6 directly); Google Calendar two-way sync; WhatsApp reminders through a business messaging provider; Postgres row-level security; group classes with capacity above one; a small Angular admin screen built on your existing front-end skills.

### Sources

- [Use Claude Code in the cloud](https://code.claude.com/docs/en/claude-code-on-the-web) (cloud sessions, teleport, auto-fix pull requests)
- [Configure cloud environments](https://code.claude.com/docs/en/cloud-environments) (installed tools, setup scripts, SessionStart hooks, network access)
