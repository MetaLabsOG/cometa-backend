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
- Treat confirmed payouts and complete manifests as terminal states.
- The raw-balance LP publisher is retired. Do not recreate it; token-token fee
  ALGO is operational balance, not an economic reserve.
- Do not silently substitute zero for unavailable chain state or price data.

## Quality Gate

```bash
pipenv verify
make sync
make quality
```

CI validates Compose but does not certify the image as immutable-deploy ready:
it runs the full quality gate on Python 3.12 and 3.14, builds the digest-pinned
Python-only image, smoke-tests the non-root runtime, scans it with Trivy, and
checks financial persistence invariants against a disposable MongoDB service.
Keep the focused lint, type, and coverage ratchets honest.

`make run` uses the production-equivalent `python app.py` entrypoint, including
critical indexes, migrations only when `MIGRATE=true`, and configured workers.
Use `make run-api` only for API-only hot reload.

Financial projector design and known standalone-Mongo limits are documented in
`docs/architecture/lp-projection.md`; outbound payout recovery is documented in
`docs/architecture/outbound-asset-transfers.md`.

## Cross-Project Changes

The canonical API contract and deploy-state log live in `~/dev/cometa/CLAUDE.md`.
For an API change, update the backend, frontend provider/types, tests, and canonical
contract as one logical unit. Record completed scoped work in `BOARD.md` without
rewriting unrelated user changes.
