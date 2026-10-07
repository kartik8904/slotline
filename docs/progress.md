# Progress log

One entry per merged session, newest first. Claude reads the latest entry at the start of
every session; you read the "What I should understand" lists before interviews.

| # | Session | Status | PR |
| --- | --- | --- | --- |
| 1 | Skeleton | Not started | |
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

**Carried forward / TODO:**
- Set `dev` as default branch and add rulesets (manual, `docs/START-HERE.md` section 2)
- Decide the known gaps in `docs/PROJECT-OVERVIEW.md` section 14 before sessions 3, 7, 9

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
