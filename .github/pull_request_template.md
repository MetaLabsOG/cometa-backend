## What changed

<!-- Describe the user-visible or operational outcome. -->

## Why

<!-- Link the GitHub issue when available and explain the failure mode or opportunity. -->

## Risk checklist

- [ ] API and frontend contracts remain compatible, or both projects were updated.
- [ ] Financial amounts stay as integer micros or `Decimal` until the API boundary.
- [ ] Retries, replay, stale data, and partial failures were considered.
- [ ] No credentials, private logs, database exports, or generated recovery data are included.

## Verification

<!-- List exact commands, tests, and any manual or on-chain checks performed. -->

## Deployment notes

<!-- Note migrations, environment changes, rollout order, and rollback steps. -->
