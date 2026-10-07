## Type
- [ ] Session <N> — <name> (feature/* → dev)
- [ ] Fix / docs / chore (→ dev)
- [ ] Promotion: dev → uat / uat → release (production) / release → main (stable)
- [ ] Hotfix (hotfix/* → release) or back-merge (release → uat/dev)

## What changed
-

## Why
-

## How to test
```bash
make lint && make test
```

## Test output
```text
<paste summary lines>
```

## Things to understand
<!-- 3–5 bullets on the trickiest parts, explained simply -->
-

## Checklist
- [ ] Base branch follows docs/BRANCHING.md (feature → dev; promotions one level at a time)
- [ ] Matches docs/plan.md (or plan/ADR updated in this PR)
- [ ] Every new endpoint has success, validation, auth and other-tenant tests
- [ ] New migration for model changes; no merged migration edited
- [ ] No secrets, no full emails/phones/tokens in logs
