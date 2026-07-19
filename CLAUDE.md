# Cometa Backend

Backend for Cometa — an Algorand DeFi platform handling liquidity pools, token swaps, staking rewards, NFT lotteries, and DEX aggregation (Tinyman, Pact, HumbleSwap, Vestige).

## Stack

- **Language**: Python 3.12 production runtime; Python 3.14 compatibility CI; Pipenv
- **Framework**: FastAPI + Uvicorn
- **Database**: MongoDB (pymongo)
- **Cache**: process-local TTL caches (Redis migration is roadmap work)
- **Blockchain**: Algorand (py-algorand-sdk, algosdk)
- **Contract state**: versioned native Reach decoder over Algorand state
- **Deployment**: Docker Compose on VPS
- **Image**: digest-pinned Python 3.12 Alpine

## Project Structure

```
app.py              — FastAPI composition, routes, startup, and workers
env.py              — Settings via pydantic-settings (from .env)
api/                — Product API, background work, wallets, and disabled lottery surface
blockchain/         — Algorand node/indexer adapters
core/               — Shared authentication, persistence, and resilience
dexes/              — DEX-specific integrations
flex/application/   — Financial use-case orchestration
flex/domain/        — Pure allocation, pricing, projection, and identity rules
flex/db/            — Mongo models, BSON codecs, repositories, and indexes
flex/tools/         — Operator tools such as manifest-driven airdrops
bot/                — Telegram bot logic
scripts/            — Deployment and management shell scripts
tests/              — Unit tests plus opt-in real-service integration tests
docs/               — Architecture decisions, operations, and audit reports
```

## Key Commands

```bash
# Local development
pipenv verify
pipenv sync --dev
make run       # production-equivalent startup, including indexes/workers
make run-api   # API-only Uvicorn reload; no migrations or workers

# Quality gate
make quality

# Current VPS-compatible Docker stack
docker compose up -d --build
docker compose logs -f app

# Production VPS (uses the parent ~/cometa/docker-compose.yml stack)
scripts/redeploy.sh     # pull + rebuild + restart the backend service
```

## Rules

- Environment config via `env.py` (pydantic-settings) — never hardcode secrets
- Use `logging` module, never `print()` — logger per module
- Background tasks in `api/background.py` — use exponential backoff for retries
- Decode only explicitly supported Reach contract versions in `flex/blockchain/contract_state.py`
- Route registration and process orchestration stay in `app.py`; Flex routes live in `flex/api.py`
- Legacy contract persistence models live in `core/db/model.py`; `api/db_model.py`
  contains only the public contract-type enum. Maintained Flex models and
  repositories live under `flex/db/`.
- Asset prices use process-local TTL caches — see `dexes/` for provider calls
- Preserve financial values as `Decimal` or integer base units until an explicit compatibility boundary
- Persist maintained Flex financial `uint64` fields through the BSON codecs in
  `flex/db/bson.py`; do not copy legacy int64/float compatibility shapes
- Outbound transfers must persist immutable signed intent before broadcast and reconcile on-chain before completion
- LP events must enter through the complete-round preflight and `MongoLpProjectionRepository`
- Keep `SYNC_STAKING_POOLS=false` until full Algorand application-group validation is implemented
- Keep `BACKGROUND_LP_PRICES_UPDATE=false` until DEX-specific economic reserves are verified
- New pricing and transaction invariants belong in pure modules under `flex/domain/`
- Run the strict mypy target before changing `core/circuit_breaker.py` or `flex/domain/`

## Cross-Project Sync

The parent `~/dev/cometa/CLAUDE.md` is loaded automatically (Claude Code ancestor chain). It contains shared API contract, deploy state, and breaking changes log. Update it after any API or deploy change.

## Linked Projects

### Frontend: metafarm-frontend

- **Path**: `~/dev/cometa/metafarm-frontend`
- **Repo**: `MetaLabsOG/metafarm-frontend`
- **Stack**: React 18 + TypeScript, Effector (state), styled-components, react-query, CRA + custom webpack
- **Connection**: Frontend connects via `REACT_APP_COMETA_API_URL` (prod: `https://api.cometa.farm/`)

Both projects are developed in parallel. **Any API change in the backend must be reflected in the frontend and vice versa.** Before modifying an API endpoint, check how the frontend uses it (`src/providers/` directory).

### API Contract (frontend → backend)

See parent `~/dev/cometa/CLAUDE.md` for the canonical API contract table. That file is the single source of truth — update it there, not here.

### Cross-Project Workflow

- **Adding a new endpoint**: implement in backend → add provider call in frontend → test both
- **Changing response shape**: update backend model → update frontend types/effector store → verify UI
- **Adding a new field to contracts**: update `ContractInfo` model → update frontend `ContractState` type
- **Price/asset changes**: backend `flex/data/` → frontend `src/providers/` + `src/common/store/prices.ts`

## Testing

Fast tests are organized by boundary under `tests/unit/`; real-service checks live
under `tests/integration/`. Run the same local quality gate used by CI before committing:

```bash
make sync
make quality
```

- Use `pytest-asyncio` for async endpoint tests
- Use `httpx.AsyncClient` with ASGI transport for endpoint integration tests
- Keep domain tests pure and deterministic; inject clocks and provider functions
- Priority: event replay/idempotency, price freshness, contract CRUD, authorization
- Exercise crash boundaries, concurrent replay, BSON `uint64` limits, and
  Indexer-lag cutovers for financial projections
- Use a dedicated test database only for integration tests; never point tests at production
- Set `MONGODB_TEST_URI` only to run the opt-in MongoDB integration suite
- Every bug fix should include a regression test when practical

## Commit Discipline

- Always commit after completing a task or logical unit of work — never leave finished work uncommitted
- Use lowercase verb, concise English: `add`, `fix`, `update`, `remove`, `refactor`
- Push after committing unless explicitly told not to
- If changes need review, commit anyway — better to fix in a follow-up than leave uncommitted
- Update task board status before committing the related work

## Task Board

Tasks in `BOARD.md`. Format: pantheon.

## Optional Diagnostic Tools

MongoDB, Algorand, and DEX inspection connectors may be available in some agent
sessions. Treat them as optional and read-only by default. Derive database and
network targets from the active environment; never assume localhost is a safe
database and never sign or broadcast a transaction without explicit task-scoped
authorization.
