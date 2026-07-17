# Cometa Backend — Task Board

> Last updated: 2026-07-17

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
| CB-077 | Immutable sidecar delivery | todo | medium | infra | Locked private dependencies installed at build time; production bind mount removed |

## Completed milestones

| Area | Status | Evidence |
| --- | --- | --- |
| Quality foundation | done | Ruff, strict domain mypy, pytest, Node tests, focused coverage ratchet, GitHub Actions |
| Precision-safe pricing | done | Decimal observations, provenance, freshness policy, guarded legacy boundary |
| Provider resilience | done | Typed fallback errors, bounded stale data, retry classification, circuit breaker |
| Replay identity | done | Deterministic nested event IDs and collection-level uniqueness constraints |
| Container baseline | done | Digest-pinned base, unprivileged user, healthcheck, bounded logs, Docker exclusions |
| API hardening | done | Header-based API authentication, production CORS allowlist, bounded LP requests |

## Working agreement

- Track sensitive security details in private GitHub advisories, not this public board.
- Add a regression test for every correctness or reliability fix.
- Keep financial values as integer micros or `Decimal` until an explicit API boundary.
- Update the frontend and shared contract documentation with every API shape change.
