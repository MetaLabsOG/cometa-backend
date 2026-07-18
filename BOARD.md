# Cometa Backend — Task Board

> Last updated: 2026-07-18

## Conventions

- **ID format**: `CB-NNN` (sequential, never reuse)
- **Statuses**: `todo` | `in_progress` | `blocked` | `done`
- **Priorities**: `critical` | `high` | `medium` | `low`
- **Tags**: `security` | `backend` | `infra` | `dx` | `arch` | `perf`
- Next available ID: **CB-078**

## Active

| ID | Task | Status | Priority | Tags | Definition of done |
| --- | --- | --- | --- | --- | --- |
| CB-073 | Public repository hardening | in_progress | critical | security, dx | Credentials rotated, history sanitized, secret protection enabled, clean-clone scan passes |
| CB-074 | Atomic event projection | todo | critical | backend, arch | Crash-safe inbox/projector with duplicate, replay, and recovery tests |
| CB-075 | Isolate transaction signing | todo | high | security, arch | Read-only API boundary; authenticated policy-limited signing service |
| CB-076 | Async persistence boundary | todo | high | backend, perf | Storage outages cannot block the event loop; timeouts and readiness covered |

## Completed milestones

| Area | Status | Evidence |
| --- | --- | --- |
| Quality foundation | done | Ruff, strict domain mypy, pytest, focused coverage ratchet, GitHub Actions |
| Precision-safe pricing | done | Decimal observations, provenance, freshness policy, guarded legacy boundary |
| Provider resilience | done | Typed fallback errors, bounded stale data, retry classification, circuit breaker |
| Replay identity | done | Deterministic nested event IDs and collection-level uniqueness constraints |
| Container baseline | done | Digest-pinned Alpine base, multi-stage non-root runtime, healthcheck, image exclusions, Trivy CI gate |
| API hardening | done | Fail-closed header authentication, trusted hosts, explicit CORS policy, bounded LP/asset/wallet requests |
| Native Reach decoding | done | Versioned global/local codecs, exact-width integers, deterministic layout tests, no private npm runtime |
| Legacy runtime removal | done | CB-077: Node/Reach sidecar and production source bind mount removed |

## Working agreement

- Track sensitive security details in private GitHub advisories, not this public board.
- Add a regression test for every correctness or reliability fix.
- Keep financial values as integer micros or `Decimal` until an explicit API boundary.
- Update the frontend and shared contract documentation with every API shape change.
