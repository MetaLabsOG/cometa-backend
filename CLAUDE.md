# Cometa Backend

Backend for Cometa — an Algorand DeFi platform handling liquidity pools, token swaps, staking rewards, NFT lotteries, and DEX aggregation (Tinyman, Pact, HumbleSwap, Vestige).

## Stack

- **Language**: Python 3.12, Pipenv
- **Framework**: FastAPI + Uvicorn
- **Database**: MongoDB (pymongo)
- **Cache**: Redis
- **Blockchain**: Algorand (py-algorand-sdk, algosdk)
- **JS interop**: Node.js sidecar in `js/` (Algorand SDK operations)
- **Deployment**: Docker Compose on VPS
- **Image**: `nikolaik/python-nodejs:python3.12-nodejs21-slim-canary`

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
pipenv install
pipenv run uvicorn app:app --reload --port 8000

# Docker
docker-compose up -d --build
docker-compose logs -f app

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
- All API routes defined in `app.py`
- MongoDB models in `api/db_model.py`
- Asset prices cached with TTL (Redis) — see `dexes/` for price fetching

## Linked Projects

### Frontend: metafarm-frontend

- **Path**: `~/cometa/dev/metafarm-frontend`
- **Repo**: `MetaLabsOG/metafarm-frontend`
- **Stack**: React 18 + TypeScript, Effector (state), styled-components, react-query, CRA + custom webpack
- **Connection**: Frontend connects via `REACT_APP_COMETA_API_URL` (prod: `https://api.cometa.farm/`)

Both projects are developed in parallel. **Any API change in the backend must be reflected in the frontend and vice versa.** Before modifying an API endpoint, check how the frontend uses it (`src/providers/` directory).

### API Contract (frontend → backend)

Routes in `app.py` + `flex.api.router`:

| Frontend Provider | Backend Endpoint | Method |
|-------------------|-----------------|--------|
| `apiProvider.ts` | `/contracts` | GET |
| `apiProvider.ts` | `/wallet/{addr}/assets` | GET |
| `apiProvider.ts` | `/wallet/{addr}/total_cost/` | GET |
| `apiProvider.ts` | `/wallet/{addr}/nfts` | GET |
| `apiProvider.ts` | `/wallet/{addr}/pools` | GET |
| `apiProvider.ts` | `/humble/pools/all` | GET |
| `apiProvider.ts` | `/contract/register` | POST |
| `apiProvider.ts` | `/lottery/swap` | POST |
| `apiProvider.ts` | `/lottery/staking` | POST |
| `apiProvider.ts` | `/lottery/claim` | PATCH |
| `flexApiProvider.ts` | `/asset` (flex router) | POST |
| `flexApiProvider.ts` | `/assets` (flex router) | POST |
| `flexApiProvider.ts` | `/asset/price` (flex router) | POST |
| `flexApiProvider.ts` | `/assets/price` (flex router) | POST |
| `apiProvider.ts` | `/lp/state/priced` (flex router) | POST |

### Cross-Project Workflow

- **Adding a new endpoint**: implement in backend → add provider call in frontend → test both
- **Changing response shape**: update backend model → update frontend types/effector store → verify UI
- **Adding a new field to contracts**: update `ContractInfo` model → update frontend `ContractState` type
- **Price/asset changes**: backend `flex/data/` → frontend `src/providers/` + `src/common/store/prices.ts`

## Task Board

Tasks in `BOARD.md`. Format: pantheon.
