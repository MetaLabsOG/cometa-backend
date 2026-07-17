# Cometa Backend

Backend for Cometa — an Algorand DeFi platform handling liquidity pools, token swaps, staking rewards, NFT lotteries, and DEX aggregation (Tinyman, Pact, HumbleSwap, Vestige).

## Stack

- **Language**: Python 3.12, Pipenv
- **Framework**: FastAPI + Uvicorn
- **Database**: MongoDB (pymongo)
- **Cache**: process-local TTL caches (Redis migration is roadmap work)
- **Blockchain**: Algorand (py-algorand-sdk, algosdk)
- **JS interop**: Node.js sidecar in `js/` (Algorand SDK operations)
- **Deployment**: Docker Compose on VPS
- **Image**: digest-pinned Python 3.12 + Node.js 22

## Project Structure

```
app.py              — FastAPI application, routes, startup
env.py              — Settings via pydantic-settings (from .env)
api/                — Core API: background tasks, DB models, stats, swaps, wallets, NFT lottery
blockchain/         — Algorand node/indexer interaction utilities
core/               — Shared core logic
dexes/              — DEX integrations (HumbleSwap, Vestige, etc.)
flex/               — Flex module (API + data)
bot/                — Telegram bot logic
farcaster/          — Farcaster integration
js/                 — Node.js sidecar for Algorand SDK calls
scripts/            — Deployment & management shell scripts
airdrop/            — Airdrop tooling
marketplaces/       — NFT marketplace integrations
metapunks/          — MetaPunks-specific logic
```

## Key Commands

```bash
# Local development
pipenv verify
pipenv sync --dev
pipenv run uvicorn app:app --reload --port 8000

# Quality gate
make quality

# Current VPS-compatible Docker stack
docker compose up -d --build
docker compose logs -f app

# Scripts (on VPS)
scripts/redeploy.sh     # pull + rebuild + restart
scripts/restart.sh       # restart containers
scripts/stop.sh          # stop all
scripts/log.sh           # tail logs
scripts/db_shell.sh      # mongo shell
scripts/backup_db.sh     # backup MongoDB
```

## Rules

- Environment config via `env.py` (pydantic-settings) — never hardcode secrets
- Use `logging` module, never `print()` — logger per module
- Background tasks in `api/background.py` — use exponential backoff for retries
- Algorand SDK calls that need Node.js go through `js/` sidecar
- Route registration and process orchestration stay in `app.py`; Flex routes live in `flex/api.py`
- MongoDB models in `api/db_model.py`
- Asset prices use process-local TTL caches — see `dexes/` for provider calls
- Preserve financial values as `Decimal` or integer base units until an explicit compatibility boundary
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

Tests are organized by boundary under `tests/unit/`. Run the same fast checks used
by CI before committing:

```bash
make sync
make quality
```

- Use `pytest-asyncio` for async endpoint tests
- Use `httpx.AsyncClient` with ASGI transport for endpoint integration tests
- Keep domain tests pure and deterministic; inject clocks and provider functions
- Priority: event replay/idempotency, price freshness, contract CRUD, authorization
- Use a dedicated test database only for integration tests; never point tests at production
- Every bug fix should include a regression test when practical

## Commit Discipline

- Always commit after completing a task or logical unit of work — never leave finished work uncommitted
- Use lowercase verb, concise English: `add`, `fix`, `update`, `remove`, `refactor`
- Push after committing unless explicitly told not to
- If changes need review, commit anyway — better to fix in a follow-up than leave uncommitted
- Update task board status before committing the related work

## Task Board

Tasks in `BOARD.md`. Format: pantheon.

## Available MCP Tools

- **MongoDB MCP** — direct database queries in Claude sessions. Use for debugging: `db.contracts.find({active: true})`, inspecting collections, verifying data integrity. Connection: `mongodb://localhost:27017/cometa`
- **Algorand MCP** — on-chain state verification, account info, asset lookups on mainnet
- **Vestige MCP** — DEX price data, pool states, trading pairs for Algorand DeFi
- **Codex MCP** — second-opinion code review via GPT-5.x. Run `review` after writing significant code
