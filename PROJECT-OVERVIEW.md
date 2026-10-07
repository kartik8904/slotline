# Slotline: complete project overview

This file explains the whole project in one place: what it is, who uses it, what it does, how it
works, and what is and isn't included. For the exact build spec see `docs/plan.md`; for diagrams
see `docs/architecture.md`.

---

## 1. What Slotline is

Slotline is a **booking backend**. It's an API that clinics, salons and similar businesses
(or the apps built for them) use to show free time slots, book appointments, and run the
automation around those appointments.

Its defining promise: **a provider can never be double-booked**, even if hundreds of people
try to book the same slot at the same moment. Postgres enforces this, not application code.

It is not an app with screens. Swagger UI (`/docs`) is the interface. Front ends, chatbots or
voice agents call the API.

**One-line pitch:** a multi-tenant booking API with a database-enforced no-double-booking
guarantee, safe retries, and a crash-safe background worker for holds, reminders, waitlists and
signed webhooks.

## 2. Why it exists

| Purpose | What it gives you |
| --- | --- |
| Portfolio project (P1, Oct–Nov 2026) | A backend that proves real engineering: concurrency, transactions, queues, CI/CD, observability |
| Interview material | Every hard choice has an ADR and a test you can walk through |
| Foundation for Vaani (later) | A voice/AI agent books appointments into Slotline through an MCP server |
| Learning | Python, FastAPI, Postgres internals, queues, DevOps; it's a new stack next to your Node/Mongo work |

## 3. The problem it solves

Booking looks simple but breaks in real life:

| Real-world failure | How Slotline prevents it |
| --- | --- |
| Two receptionists or two customers book the same slot at the same moment | Postgres exclusion constraint rejects the second one; client gets `409 slot_unavailable` |
| Customer's phone retries a request after a timeout and creates two bookings | `Idempotency-Key` header; the retry gets the original response |
| Customer starts booking, abandons it, slot stays blocked forever | Holds expire after 5 minutes automatically |
| Reminder sent for an appointment that was cancelled | Reminder job re-checks the booking before sending |
| Server crashes and the confirmation email is lost | Email job is saved in the same transaction as the booking; worker retries it |
| One clinic sees another clinic's data | Every query is scoped by `org_id` from the credential; foreign IDs return 404 |
| A cancelled slot sits empty while people wanted it | Waitlist automatically offers the freed slot |

## 4. Who uses it

| Actor | Who they are | How they authenticate | What they do |
| --- | --- | --- | --- |
| **Owner** | Clinic or salon owner | Email + password (JWT) | Everything staff can, plus manage staff users, API keys, webhooks |
| **Staff** | Receptionist, manager | Email + password (JWT) | Manage providers, services, hours, time off, customers, bookings |
| **Machine client** | A website, mobile app, chatbot or Vaani | API key (`sl_live_…`) | Search availability, hold, book, reschedule, cancel, waitlist |
| **Customer** | Patient or salon client | Doesn't log in in v1 | Receives emails; is booked on their behalf by staff or a machine client |
| **Webhook receiver** | The business's own system | Verifies HMAC signature | Receives events like `booking.confirmed` |

## 5. Core concepts

| Concept | Meaning | Example |
| --- | --- | --- |
| Organisation (tenant) | One business; all data belongs to one | "Smile Dental, Ahmedabad" |
| Provider | A person or room that can be booked | "Dr Mehta", "Chair 2" |
| Service | What's booked, with duration and buffer | "Cleaning, 30 min + 10 min clean-up" |
| Availability rule | Weekly working hours per provider | Mon–Fri 09:00–17:00 |
| Time off | Leave, holidays, breaks | Dr Mehta off 10–12 Nov |
| Customer | Person being booked | Name, E.164 phone, email, consent flags |
| Hold | Temporary reservation while confirming | Expires in 5 min if not confirmed |
| Booking | Confirmed appointment | Status: held → confirmed → completed |
| Waitlist entry | Someone wanting a time that was full | "Any cleaning, Tue 2–6 pm" |
| Webhook endpoint | URL that receives signed event notifications | `https://clinic.example/hooks` |

## 6. Features (v1)

**Accounts and security**
- Organisation signup creates the owner user
- Staff login with 15-minute access tokens and rotating 30-day refresh tokens
- Refresh-token reuse detection (revokes the whole token family)
- API keys for machines: hashed, shown once, scoped, revocable
- Owner / staff roles; rate limits; lockout after 10 failed logins in 15 minutes

**Catalogue**
- Providers, services (duration, buffer, display price in paise), which provider offers which service
- Weekly working hours replaced in one atomic call
- Time off, blocked if it overlaps confirmed bookings unless forced
- Customers with search by phone or name

**Availability and booking**
- Computed availability: working hours − time off − active bookings, 15-min steps, 2-hour minimum notice, 31-day max range, time-zone aware
- Hold → confirm, or direct booking in one step
- Reschedule (atomic), cancel with reason, mark completed, mark no-show
- Full event history per booking
- Idempotent writes; optimistic locking for edits (`If-Match`)

**Automation (background worker)**
- Hold expiry every 30 seconds
- Confirmation email; reminders at 24 h and 2 h (configurable per org)
- Reschedule and cancellation notices (old reminders cancelled)
- Waitlist offers: freed slot → 15-minute hold for the next matching person → offer email
- Auto no-show flag for staff review
- Daily schedule digest to providers at 19:00 local time
- Signed webhooks with retries (1 m, 5 m, 30 m, 2 h, 12 h)
- Nightly housekeeping

**Operations**
- Health checks, structured logs, traces, metrics, error tracking
- Seven-check CI, automatic staging deploy, one-click production deploy, rollback by image SHA

## 7. A day in the life (end-to-end example)

1. **Setup.** Smile Dental signs up. The owner adds Dr Mehta (Mon–Fri 9–5, Asia/Kolkata) and "Cleaning" (30 min + 10 min buffer), then creates an API key for the clinic's website.
2. **Search.** A patient on the website picks Cleaning for next week. The site calls `GET /availability` and shows 09:00, 09:45, 10:30, …
3. **Hold.** The patient picks Tue 10:30. The site calls `POST /holds` with an idempotency key. Slotline inserts a `held` booking blocking 10:30–11:10 and returns `hold_expires_at` 5 minutes out.
4. **Race.** At the same second another patient tries 10:30 with Dr Mehta. Postgres rejects the insert; they get `409 slot_unavailable` and pick another time.
5. **Confirm.** The patient enters details; the site calls `POST /holds/{id}/confirm`. Status becomes `confirmed`. In the same transaction an outbox event `booking.confirmed` is written.
6. **Automation.** Within a second the worker sends a confirmation email, schedules reminders for Mon 10:30 and Tue 08:30, and delivers a signed webhook to the clinic's system.
7. **Cancel.** On Monday the patient cancels. Reminders are cancelled, a notice is emailed, and the waitlist job gives the 10:30 slot to the first matching waitlist person as a 15-minute hold with an offer email.
8. **Visit.** Someone attends; staff mark it `completed`. If nobody marks it within 30 minutes of the end, it's flagged for review.
9. **Evening.** At 19:00 Dr Mehta gets tomorrow's schedule by email.

## 8. How it works (summary)

- **Two processes, one codebase:** the API (FastAPI) handles requests; the worker handles slow, retryable work. Both use one Postgres database.
- **Postgres does three jobs:** stores data, guarantees no overlap (exclusion constraint on `tstzrange`), and acts as the job queue (`FOR UPDATE SKIP LOCKED`). Redis is used only for rate limits.
- **Transactional outbox:** a booking change and its "events to process" row commit together, so automation can be delayed but never lost or wrong.
- **Layered code:** routes → services (rules + transactions) → repositories (SQL with `org_id`); `domain/` holds pure logic (slot maths, state machine, time zones) that's unit-tested without a database.
- **One error shape:** RFC 9457 Problem Details with stable `code` values.

Diagrams for each of these are in `docs/architecture.md`.

## 9. Tech stack

| Area | Choice |
| --- | --- |
| Language | Python 3.13, managed with uv |
| API | FastAPI, Pydantic v2 |
| Database | PostgreSQL 17 + btree_gist; SQLAlchemy 2 async + asyncpg; Alembic |
| Cache / rate limit | Redis 7 |
| Auth | PyJWT, argon2id |
| Email | Notifier interface; Mailpit locally; Resend, Postmark or SES in production |
| Observability | structlog, OpenTelemetry, Prometheus, Sentry |
| Testing | pytest, pytest-asyncio, httpx, Hypothesis, Schemathesis, Locust |
| Quality | ruff, mypy --strict, pre-commit |
| Delivery | Docker, GitHub Actions, GHCR, Fly.io or Render (AWS ECS + RDS later) |

## 10. Data model (19 tables)

| Group | Tables |
| --- | --- |
| Tenancy and access | organizations, users, refresh_tokens, api_keys |
| Catalogue | providers, services, provider_services, availability_rules, time_off, customers |
| Bookings | bookings, booking_events, waitlist_entries |
| Reliability | idempotency_keys, outbox_events, jobs |
| Messaging | notifications, webhook_endpoints, webhook_deliveries |

Every business table has `org_id`, a UUID v7 `id`, and UTC `created_at` / `updated_at`.

## 11. API at a glance

All under `/api/v1`. About 30 endpoint groups:

| Area | Endpoints |
| --- | --- |
| Auth | signup, login, refresh, logout, /me |
| Admin | /api-keys, /users, /webhooks (+ deliveries, retry) |
| Catalogue | /providers (+ availability, time-off), /services, /customers |
| Booking | /availability, /holds, /holds/{id}/confirm, /bookings (+ reschedule, cancel, complete, no-show), /waitlist |
| Ops | /health/live, /health/ready, /metrics (internal) |

## 12. Quality bar ("production-ready" for this project)

| Claim | Proof |
| --- | --- |
| No double bookings | 200 concurrent holds on one slot → exactly one 201 |
| Safe retries | 50 identical requests with one key → one booking |
| Reliable automation | 2 workers × 500 jobs → each runs exactly once |
| Tenant isolation | Every endpoint called with another tenant's IDs → 404 |
| API matches its spec | Schemathesis fuzzing, no 500s |
| Fast enough | p95 for holds < 300 ms at 50 requests/second |
| Safe delivery | 7 CI checks, staging + smoke tests, manual approval, rollback by SHA |
| Tested | 85% coverage overall, 95% for services and domain |

## 13. Out of scope for v1

Payments · group classes · recurring bookings · a full web front end · SMS / WhatsApp ·
calendar sync · customer self-service login.

## 14. Known gaps to decide before building

The plan is detailed but these are **not yet specified**. Decide each before the session listed.

| Gap | Why it matters | Decide before |
| --- | --- | --- |
| Password reset and staff invite acceptance | `/users` "invites" staff but there's no accept-invite or reset-password flow | Session 3 |
| Customer links in emails (cancel link, claim waitlist offer) | Customers don't log in, so these need signed, expiring public tokens and public endpoints | Session 9 |
| Customer export and delete endpoints | Listed in the security checklist (GDPR / DPDP) but not in the endpoint table or any session | Session 10 or 11 |
| General admin audit trail | "Admin audit trail" is in scope, but only booking history is designed | Session 7 |
| Email sending domain (SPF, DKIM, DMARC) | Without it reminders land in spam | Session 9 |
| Consent handling | Customers have consent flags but no rule for when reminders are allowed | Session 9 |
| Cost ceiling | Hosting, managed Postgres and email provider costs per month | Session 12 |

## 15. Roadmap after v1

1. MCP server exposing find_slots, hold, confirm, reschedule, cancel (becomes Vaani's booking tool)
2. Google Calendar two-way sync
3. WhatsApp reminders through a business messaging provider
4. Postgres row-level security as a second tenant guard
5. Group classes with capacity above one
6. A small Angular admin screen
7. Move hosting to AWS ECS + RDS with Terraform

## 16. Timeline

About 6 weeks at ~22 hours a week, 12 sessions, 2 per week. Session details and prompts are in
`docs/session-prompts.md`; progress is logged in `docs/progress.md`.
