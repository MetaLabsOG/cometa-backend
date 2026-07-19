# Cometa Backend — Task Board

> Last updated: 2026-07-19

## Conventions

- **ID format**: `CB-NNN` (sequential, never reuse)
- **Statuses**: `todo` | `in_progress` | `blocked` | `done`
- **Priorities**: `critical` | `high` | `medium` | `low`
- **Tags**: `security` | `backend` | `infra` | `dx` | `arch` | `perf`
- Next available ID: **CB-097**

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
| CB-084 | Disable unverified LP pricing | done | critical | backend, arch | Raw-account-balance publisher is removed; startup purges its legacy rows and every stored-price read rejects them |
| CB-085 | Remove repository credibility drift | done | medium | dx, arch | Public claims match verified behavior, local sync selects Python 3.12, and the unrelated EVM sample is removed |
| CB-086 | Reconcile legacy lottery payouts | done | critical | security, backend | Pre-intent lottery draws fail closed until manual reconciliation; new draws use durable payout states |
| CB-087 | Preserve terminal payout states | done | high | backend, arch | Confirmed transfer intents and complete airdrop manifests cannot regress under stale concurrent workers |
| CB-088 | Separate LP ledger from pricing | done | critical | backend, arch | Raw balances never publish prices; fees are replay-safe events and operational ALGO is isolated from reserves |
| CB-089 | Migrate canonical asset supply | done | high | backend, arch | Financial reads trust only Indexer-provenanced base units, migrate atomically, and fail closed on duplicate asset IDs |
| CB-090 | Claim staking lottery entitlements atomically | done | critical | backend, arch | Concurrent and crash-recovery paths converge on one draw generation in real MongoDB |
| CB-091 | Bound outbound signer fees and network | done | critical | security, backend | Suggested and persisted transactions enforce a configured fee ceiling and canonical genesis before network I/O |
| CB-092 | Validate Algorand numeric boundaries | done | high | backend, arch | Indexer events and snapshots reject coercion, negatives, duplicates, and uint64 overflow before persistence |
| CB-093 | Reserve one-of-one lottery inventory | todo | high | backend, arch | A re-enabled lottery atomically reserves NFT inventory and reconciles release/finalization |
| CB-094 | Replace retired LP pricing with verified adapters | todo | high | backend, arch | DEX-specific app state proves economic reserves; donation and excess-balance adversarial tests pass |
| CB-095 | Reject poisoned price chronology | done | high | backend, arch | Future-dated quotes fail before persistence and a valid quote replaces legacy future timestamps |
| CB-096 | Enforce standalone financial indexes | done | high | backend, arch | Operator airdrops and LP discovery require unique immutable business keys before concurrent upserts |

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
