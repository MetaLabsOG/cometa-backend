# Cometa Backend — Task Board

> Last updated: 2026-07-19

## Conventions

- **ID format**: `CB-NNN` (sequential, never reuse)
- **Statuses**: `todo` | `in_progress` | `blocked` | `done`
- **Priorities**: `critical` | `high` | `medium` | `low`
- **Tags**: `security` | `backend` | `infra` | `dx` | `arch` | `perf`
- Next available ID: **CB-086**

## Active

| ID | Task | Status | Priority | Tags | Definition of done |
| --- | --- | --- | --- | --- | --- |
| CB-073 | Public repository hardening | in_progress | critical | security, dx | Credentials rotated, history sanitized, secret protection enabled, clean-clone scan passes |
| CB-074 | Atomic event projection | in_progress | critical | backend, arch | LP projector is crash-safe; replace the disabled legacy staking projector with verified grouped events and recovery tests |
| CB-075 | Isolate transaction signing | todo | high | security, arch | Read-only API boundary; authenticated policy-limited signing service |
| CB-076 | Async persistence boundary | todo | high | backend, perf | Storage outages cannot block the event loop; timeouts and readiness covered |
| CB-078 | Replay-safe outbound asset payouts | done | critical | security, backend, arch | Exact allocations, immutable airdrop manifests, persisted signed intents, on-chain reconciliation, and regression tests |
| CB-079 | Crash-safe LP projection | done | critical | backend, arch | Decimal128 balances, ordered per-state CAS cursor, fenced round checkpoint, snapshot guards, and crash/concurrency tests |
| CB-080 | Financial read-model regressions | done | medium | backend | Reward decimals use the reward asset and request ordering never mutates cached contract state |
| CB-081 | Fence expired sync workers | done | critical | backend, arch | A worker cannot commit a financial round after its lease expires, with unit and real-Mongo regressions |
| CB-082 | Verify Mongo financial invariants | done | high | backend, infra | CI proves CAS replay, marker repair, BSON promotion, uniqueness, and lease fencing against a disposable pinned MongoDB |
| CB-083 | Refresh public engineering docs | done | medium | dx, arch | Runtime commands, Python support, architecture boundaries, API shapes, and cross-project contract are current |
| CB-084 | Disable unverified LP pricing | done | critical | backend, arch | Legacy raw-account-balance LP pricing is independently default-off until DEX economic reserves are verified |
| CB-085 | Remove repository credibility drift | done | medium | dx, arch | Public claims match verified behavior, local sync selects Python 3.12, and the unrelated EVM sample is removed |

## Completed milestones

| Area | Status | Evidence |
| --- | --- | --- |
| Quality foundation | done | Ruff, strict domain mypy, pytest, focused coverage ratchet, GitHub Actions |
| Precision-safe pricing | done | Decimal observations, provenance, freshness policy, guarded legacy boundary |
| Provider resilience | done | Typed fallback errors, bounded stale data, retry classification, circuit breaker |
| Replay identity | done | Deterministic nested event IDs and collection-level uniqueness constraints |
| LP financial ledger | done | Marker-gap recovery, uint64-safe BSON operations, full-block preflight, snapshot coverage guards, and fenced round CAS |
| Container baseline | done | Digest-pinned Alpine base, multi-stage non-root runtime, healthcheck, image exclusions, Trivy CI gate |
| API request hardening | done | Fail-closed configured header checks, trusted hosts, explicit CORS policy, bounded selectors and wallet expansion |
| Native Reach decoding | done | Versioned global/local codecs, exact-width integers, deterministic layout tests, no private npm runtime |
| Legacy runtime removal | done | CB-077: Node/Reach sidecar and production source bind mount removed |

## Working agreement

- Track sensitive security details in private GitHub advisories, not this public board.
- Add a regression test for every correctness or reliability fix.
- Keep financial values as integer micros or `Decimal` until an explicit API boundary.
- Update the frontend and shared contract documentation with every API shape change.
