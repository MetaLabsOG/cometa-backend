# Backend Agent Briefing

Read this file and the root `AGENTS.md` before changing code. `BOARD.md` records
work status; it does not override repository safety rules or the current user request.

## Working Order

1. Inspect the relevant implementation and its tests.
2. Check frontend consumers in `~/dev/cometa/metafarm-frontend/src/providers/`
   before changing an endpoint or response shape.
3. Preserve external behavior unless the task explicitly authorizes a contract change.
4. Add or update a regression test with the implementation.
5. Run the narrow checks while iterating, then the complete quality gate.

## Architecture Boundaries

- `app.py` owns application assembly, route registration, and process orchestration.
- Pure pricing and transaction invariants belong in `flex/domain/`.
- MongoDB and provider adapters stay outside domain modules.
- Synchronous SDK or HTTP work must not block an async request path.
- Financial amounts remain integer base units or `Decimal` until an explicit
  compatibility boundary.
- Circuit breakers are process-local resilience controls, not cross-process coordination.

## Safety Boundaries

- Never expose or commit mnemonics, tokens, private keys, `.env`, recovery data,
  or full sensitive payloads.
- Do not execute signing, refunds, deployments, database migrations, or production
  scripts unless the user explicitly requests that external action.
- Validate on-chain and provider payloads before persistence.
- Preserve idempotency for transaction replay and financial background jobs.
- Do not silently substitute zero for unavailable chain state or price data.

## Quality Gate

```bash
pipenv verify
pipenv sync --dev
make quality
```

CI validates Compose but does not certify the image as immutable-deploy ready:
the private Node sidecar package-auth blocker is documented in `README.md`. Keep the
focused lint, type, and coverage ratchets honest.

## Cross-Project Changes

The canonical API contract and deploy-state log live in `~/dev/cometa/CLAUDE.md`.
For an API change, update the backend, frontend provider/types, tests, and canonical
contract as one logical unit. Record completed scoped work in `BOARD.md` without
rewriting unrelated user changes.
