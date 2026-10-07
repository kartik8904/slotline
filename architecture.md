# Slotline architecture: how everything flows

Read this when you want to understand *why* the code is shaped the way it is.
Diagrams are Mermaid; GitHub renders them automatically. Section numbers match the
sessions that build each part.

---

## 1. The big picture

Two processes, one codebase, one database. Postgres is both the store and the job queue.

```mermaid
flowchart LR
  subgraph Clients
    S[Staff via Swagger / admin UI]
    M[Machine clients<br/>e.g. Vaani via API key]
  end

  subgraph API["API process (FastAPI, 2 instances)"]
    MW[Middleware<br/>request-id · logging · rate limit · idempotency]
    R[Routes api/v1]
    SV[Services<br/>business rules + transactions]
    RP[Repositories<br/>SQL, always org_id]
    D[domain/<br/>pure logic]
  end

  subgraph WK["Worker process (1+ instances)"]
    L[Loop: claim jobs<br/>FOR UPDATE SKIP LOCKED]
    SC[Scheduler<br/>periodic jobs]
    H[Job handlers]
  end

  PG[(Postgres 17<br/>data + outbox + jobs)]
  RD[(Redis<br/>rate limits only)]
  EM[Email provider<br/>Mailpit locally]
  WH[Customer webhook URLs]

  S --> MW
  M --> MW
  MW --> R --> SV --> RP --> PG
  SV --> D
  MW <--> RD
  PG -- outbox_events / jobs --> L
  SC --> PG
  L --> H
  H --> EM
  H --> WH
  H --> PG
```

**The one-sentence version:** the API changes data and writes "something needs to happen"
rows in the *same transaction*; the worker picks those rows up and does the slow, retryable
work (email, webhooks, expiry).

Why two processes? A request should finish in milliseconds. Sending email or calling a
customer's webhook can take seconds or fail. Keeping that out of the request makes the API
fast and makes retries safe.

---

## 2. Inside one request (sessions 1, 3, 7)

```mermaid
sequenceDiagram
  autonumber
  participant C as Client
  participant MW as Middleware
  participant RT as Route
  participant SV as Service
  participant RP as Repository
  participant PG as Postgres

  C->>MW: POST /api/v1/holds<br/>X-API-Key, Idempotency-Key
  MW->>MW: assign X-Request-ID, start log context
  MW->>MW: rate limit check (Redis)
  MW->>PG: insert idempotency key (ON CONFLICT DO NOTHING)
  alt key seen before with same body
    MW-->>C: replay stored response
  end
  MW->>RT: request
  RT->>RT: auth → principal(org_id, scopes); validate body (Pydantic)
  RT->>SV: create_hold(principal, data)
  SV->>PG: BEGIN
  SV->>RP: expire stale holds in range
  SV->>RP: insert booking (status=held)
  SV->>RP: insert booking_event + outbox_event
  SV->>PG: COMMIT
  SV-->>RT: booking
  RT-->>MW: 201 + body
  MW->>PG: store response under idempotency key
  MW-->>C: 201 Created
```

What each layer is allowed to do:

| Layer | Folder | Does | Never does |
| --- | --- | --- | --- |
| Middleware | `middleware/` | request ID, logs, rate limit, idempotency | business rules |
| Route | `api/v1/` | parse HTTP, auth, call one service, map to response | SQL, commit |
| Service | `services/` | rules, transactions, call domain + repos | know about HTTP |
| Domain | `domain/` | pure maths: slots, state machine, time zones | any I/O |
| Repository | `repositories/` | SQL, always filtered by `org_id` | business decisions |

---

## 3. Multi-tenancy (session 3)

Every business table has `org_id`. The org comes from the credential:

```mermaid
flowchart LR
  T[JWT or API key] --> P[deps.current_principal]
  P -->|principal.org_id| SV[Service]
  SV -->|org_id first arg| RP[Repository]
  RP -->|WHERE org_id = :org| PG[(Postgres)]
```

- A request can never *name* a tenant; URLs carry only resource IDs.
- If org A asks for org B's booking ID, the query finds nothing → **404** (not 403, which
  would confirm the ID exists).
- A test calls every endpoint as org A with org B's IDs and expects 404 everywhere.

Auth types: staff log in (15-minute access JWT + rotating 30-day refresh token); machines use
hashed API keys (`sl_live_…`, shown once). Reusing an old refresh token revokes the whole
token family (someone stole it).

---

## 4. Availability: computed, never stored (session 5)

There is no "slots" table. Open start times are calculated on demand:

```mermaid
flowchart TD
  A[Weekly rules<br/>Mon 09:00–17:00 ...] --> B[Expand into real intervals<br/>for the date range,<br/>in provider's time zone → UTC]
  B --> C[Subtract time_off]
  C --> D[Subtract 'blocked' range of<br/>held + confirmed bookings]
  D --> E[Walk free intervals in 15-min steps;<br/>keep starts where duration + buffer fits]
  E --> F[Drop past starts and<br/>starts inside minimum notice]
  F --> G[Start times grouped by provider]
```

Availability is a **hint**. Two people can see the same free slot; only the hold/booking
call decides who gets it (section 5).

Time zones: store UTC everywhere; use the provider's IANA zone only to expand working hours
and for display. A DST test week (Europe/Dublin) proves 09:00 stays 09:00 local.

---

## 5. The double-booking guarantee (session 6) — the heart of the project

```sql
CONSTRAINT bookings_no_overlap EXCLUDE USING gist (
  provider_id WITH =,
  blocked     WITH &&
) WHERE (status IN ('held', 'confirmed'))
```

Read it as: *"for active bookings, no two rows may have the same provider AND overlapping
`blocked` ranges."* Postgres enforces this atomically, even with 200 requests at once.

```mermaid
sequenceDiagram
  participant A as Request A
  participant B as Request B
  participant PG as Postgres

  A->>PG: INSERT booking 10:30–11:00 (Dr Mehta)
  B->>PG: INSERT booking 10:30–11:00 (Dr Mehta)
  PG-->>A: OK (commits first)
  PG-->>B: ERROR 23P01 exclusion_violation
  Note over B: service maps 23P01 → 409 slot_unavailable
```

Why not "SELECT to check, then INSERT"? Both requests can run the SELECT before either
inserts, both see the slot free, both insert. That race is exactly what the constraint
removes.

The five rules that make it work:

1. **Half-open ranges** `[start, end)` so 10:00–10:30 and 10:30–11:00 don't overlap.
2. **`blocked` = `during` + buffer**: a 30-min service with 10-min clean-up blocks 40.
3. **Expire stale holds in the same transaction** before inserting, so a hold that
   expired one second ago doesn't block anyone while waiting for the worker.
4. **Translate `23P01` → 409**, never a 500.
5. **Reschedule = one UPDATE** of `during` + `blocked`; if it conflicts, the original stays.

---

## 6. Booking lifecycle (sessions 6, 7)

```mermaid
stateDiagram-v2
  [*] --> held: POST /holds
  [*] --> confirmed: POST /bookings (direct)
  held --> confirmed: POST /holds/{id}/confirm
  held --> expired: hold_expires_at passes
  held --> cancelled: cancel
  confirmed --> confirmed: reschedule
  confirmed --> cancelled: cancel
  confirmed --> completed: staff marks attended
  confirmed --> no_show: staff marks missed
  expired --> [*]
  cancelled --> [*]
  completed --> [*]
  no_show --> [*]
```

- Only `held` and `confirmed` are **active** (count in the constraint).
- The allowed transitions are a table in `domain/booking_state.py`; anything else →
  `409 invalid_transition`.
- Every transition appends a `booking_events` row (audit trail) and an `outbox_events` row.
- Confirming after expiry → `410 hold_expired`.

Safety for retries and edits:

| Problem | Mechanism | Result |
| --- | --- | --- |
| Client retries a POST after a timeout | `Idempotency-Key` header, stored 24 h | Same response replayed, no duplicate booking |
| Same key, different body | request hash compare | `422 idempotency_key_reused` |
| Two staff edit one booking | `If-Match: <version>` | Second gets `412 precondition_failed` |

---

## 7. The worker: outbox + jobs (session 8)

```mermaid
flowchart TD
  subgraph TX["One API transaction"]
    B1[UPDATE/INSERT booking] --> B2[INSERT booking_events] --> B3[INSERT outbox_events]
  end
  B3 -- NOTIFY / 5s poll --> W1[Worker: read unpublished outbox events]
  W1 --> W2[Create jobs with dedupe_key<br/>+ webhook deliveries]
  W2 --> W3[Mark event published_at]
  W3 --> W4[Claim due jobs:<br/>SELECT ... FOR UPDATE SKIP LOCKED LIMIT 20]
  W4 --> W5{Handler succeeds?}
  W5 -- yes --> W6[status = done]
  W5 -- no --> W7{attempts < max?}
  W7 -- yes --> W8[status = queued,<br/>run_at += backoff + jitter]
  W7 -- no --> W9[status = dead → alert]
```

Key ideas, in plain words:

- **Transactional outbox:** the "send a confirmation" row commits *with* the booking. If the
  transaction rolls back, the row never existed, so no email for a booking that doesn't exist.
  If the worker crashes, the row is still there, so the email is delayed, never lost.
- **SKIP LOCKED:** many workers can poll the same table; each row is locked by whoever grabs
  it first and skipped by the others. A crashed worker's lock times out (`locked_until`).
- **Exactly-once effect:** jobs can run more than once (retries), so every handler re-reads
  the booking and does nothing if it changed, and `dedupe_key` has a unique index.
- **Graceful shutdown:** on SIGTERM, stop claiming, finish in-flight jobs (≤ 25 s), exit.

---

## 8. Automations (sessions 8–10)

```mermaid
flowchart LR
  E1[booking.confirmed] --> J1[confirmation email]
  E1 --> J2[reminder jobs at T-24h, T-2h]
  E2[booking.rescheduled] --> J3[notice + cancel old reminders + new reminders]
  E3[booking.cancelled] --> J4[cancel notice]
  E3 --> J5[waitlist offer]
  E4[booking.expired] --> J5
  J5 --> J6[15-min hold for first matching<br/>waitlist entry + offer email]
  J6 -- unclaimed --> E4
  ALL[every outbox event] --> J7[signed webhook to subscribed endpoints]
  T1[every 30 s] --> J8[expire stale holds]
  T2[19:00 org time] --> J9[daily digest to providers]
  T3[nightly] --> J10[housekeeping deletes]
```

Webhooks are signed: `HMAC-SHA256(secret, timestamp + "." + body)` in the
`Slotline-Signature` header. Receivers verify the signature, reject timestamps older than
5 minutes, and dedupe on event ID. Retries: 1 m, 5 m, 30 m, 2 h, 12 h, then dead.
Webhook URLs must be HTTPS and must not resolve to private IPs (SSRF guard).

---

## 9. Delivery pipeline (sessions 2, 12)

```mermaid
flowchart LR
  PR[Pull request] --> CI{7 CI checks<br/>lint · types · test · concurrency ·<br/>migrations · contract · security}
  CI -- fail --> FIX[Auto-fix / you fix]
  FIX --> PR
  CI -- pass --> MERGE[Squash-merge to main]
  MERGE --> IMG[Build image once,<br/>tag with SHA → GHCR]
  IMG --> STG[Migrate + deploy staging]
  STG --> SMK{Smoke tests}
  SMK -- fail --> STOP[Stop; prod untouched]
  SMK -- pass --> APR[Manual approval]
  APR --> PROD[Migrate + deploy production]
  PROD --> REL[GitHub release notes]
```

Same image in staging and production, so what passed staging is byte-for-byte what ships.
Rollback = redeploy the previous SHA, which is why migrations must be backwards-compatible.

---

## 10. Observability (session 11)

One booking can be followed end to end: the API writes the trace ID onto the outbox event,
the worker continues that trace, so a single trace shows *request → DB insert → job → email*.

| Signal | Tool | Answers |
| --- | --- | --- |
| Logs | structlog JSON with `request_id`, `org_id`, `job_id` | What happened to this request? |
| Traces | OpenTelemetry | Where was the time spent? |
| Metrics | Prometheus | Is it healthy right now? (5xx rate, p95, queue age, dead jobs) |
| Errors | Sentry | What crashed, in which release? |

---

## 11. Glossary

| Term | Meaning |
| --- | --- |
| Tenant / org | One clinic or salon; all its data carries its `org_id` |
| Provider | A person or room that can be booked |
| Hold | A temporary booking (default 5 min) while a customer confirms |
| `during` / `blocked` | What the customer sees / what's unavailable incl. buffer |
| Exclusion constraint | Postgres rule that no two rows may "conflict" on given operators |
| `tstzrange` | Postgres type for a time range with time zone |
| Outbox | Table of events written in the same transaction as the data change |
| SKIP LOCKED | Postgres option: skip rows another transaction has locked |
| Idempotency key | Client-chosen ID that makes retrying a request safe |
| Problem Details | Standard JSON error shape (RFC 9457) |
| ADR | Architecture Decision Record: one page on a choice and its trade-off |

## 12. Questions to be able to answer (interview prep)

1. Why an exclusion constraint instead of `SELECT … FOR UPDATE` or an application lock?
2. What happens if the worker crashes halfway through sending a reminder?
3. How do you guarantee a reminder is never sent for a cancelled booking?
4. Why 404 instead of 403 for another tenant's ID?
5. Why Postgres as a queue instead of Redis/RabbitMQ, and when would you switch?
6. How does a client safely retry a timed-out booking request?
7. How do you deploy a column rename without downtime?
8. Walk through the 200-concurrent-request test and what it proves.
