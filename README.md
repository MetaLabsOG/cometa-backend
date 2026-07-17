# Cometa Backend

[![CI](https://github.com/MetaLabsOG/cometa-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/MetaLabsOG/cometa-backend/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688.svg)](https://fastapi.tiangolo.com/)

Production backend for **Cometa**, an Algorand DeFi platform that aggregates farms, staking programs, liquidity pools, wallet positions, and token prices across multiple DEXes.

This repository is primarily a data and orchestration service: it normalizes on-chain state, enriches it with market data, maintains read models in MongoDB, and exposes a stable API to the Cometa frontend.

## Engineering Highlights

- Multi-source price routing across Vestige, Tinyman, Pact, and HumbleSwap.
- Precision-safe `Decimal` pricing value objects with explicit source, observation time,
  freshness policy, and a guarded legacy-float boundary.
- Deterministic transaction event IDs for safe replay of nested Algorand transfers.
- Executor wrappers around synchronous Algorand SDK calls in latency-sensitive paths.
- Background workers for contract state, asset prices, LP reserves, and pool synchronization.
- In-process TTL caches and MongoDB indexes for hot lookups; Redis integration remains roadmap work.
- Python-to-Node.js interoperability over a bounded Unix socket protocol for Reach SDK operations.
- Constant-time API-key verification and a strict production CORS allowlist.
- Single-operation MongoDB upserts with explicit unique-index requirements and regression tests.
- Process-local circuit breakers with single-probe half-open recovery.

## Architecture

```mermaid
flowchart LR
    UI[Cometa frontend] --> API[FastAPI routes]
    API --> DOMAIN[Domain and pricing services]
    DOMAIN --> MONGO[(MongoDB read models)]
    DOMAIN --> CACHE[(Process-local TTL caches)]
    DOMAIN --> CHAIN[Algorand node + indexer]
    DOMAIN --> DEX[DEX and price APIs]
    DOMAIN --> SOCKET[Unix socket]
    SOCKET --> NODE[Node.js Reach sidecar]
    WORKERS[Background workers] --> DOMAIN
```

The API serves query-oriented read models while workers reconcile external state. Several provider paths use fallbacks; uniform timeout, stale-data, and exactly-once projection semantics are tracked as explicit architecture work rather than hidden assumptions.

## Repository Layout

| Path | Responsibility |
| --- | --- |
| `app.py` | FastAPI application, routes, startup, and process orchestration |
| `api/` | Background tasks, wallet logic, statistics, and notifications |
| `blockchain/` | Algorand node/indexer adapters |
| `core/` | Shared domain logic, authentication, caching, and persistence |
| `dexes/` | DEX-specific integrations |
| `flex/domain/` | Pure pricing invariants and deterministic transaction parsing |
| `flex/` | Asset, pool, provider, persistence, and migration pipelines |
| `js/` | Reach/Algorand SDK sidecar |
| `scripts/` | Deployment, backup, recovery, and diagnostic tools |
| `tests/unit/` | Fast, isolated domain and infrastructure regression tests |

## Local Development

Requirements: Python 3.12, Pipenv, Node.js 22, MongoDB, and access to an Algorand node/indexer.

```bash
cp .env.example .env
# Fill the required credentials locally; never commit .env.
pipenv verify
pipenv sync --dev
pipenv run python app.py
```

For API-only route development without migrations, workers, or the JS sidecar, use
`pipenv run uvicorn app:app --reload --port 8000`. The sidecar is disabled by
default; set `ENABLE_JS=true` only after installing its locked private dependencies
with a read-only `NODE_AUTH_TOKEN`.

Run the complete local quality gate:

```bash
make quality
```

CI runs the full test suite and applies a 75% focused coverage ratchet to maintained
domain and infrastructure modules. It does not present that number as whole-repository
coverage; legacy modules join the ratchet after they gain isolated test seams.
Individual targets such as `make lint`, `make format-check`, `make typecheck`, and
`make test` are available for faster iteration.

Run the containerized stack with:

```bash
docker compose up -d --build
docker compose logs -f app
```

The image uses Python 3.12 and Node.js 22 from a digest-pinned base, installs the
committed Python lockfile into the system environment, and runs as an unprivileged
user. Pin `MONGODB_IMAGE` and `ALGOD_IMAGE` to versions validated against the
deployed data before a production rollout; the compatibility defaults remain
unchanged to avoid an implicit database or node upgrade.

The current VPS Compose path still mounts the checkout because the private Reach
sidecar dependencies require authenticated GitHub Packages access. CI deliberately
does not label this image production-ready. Before removing the mount, add a
read-only `NODE_AUTH_TOKEN` as a BuildKit secret, install the committed Node lock,
smoke-test the sidecar, and only then enable an immutable deploy.

## API Surface

Representative endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /status` | Service version and Algorand network |
| `GET /contracts` | Farm/distribution contract catalog |
| `GET /contracts/user/{address}` | Contracts used by a wallet |
| `GET /contracts/farm/enriched` | Contracts enriched with assets and prices |
| `POST /assets/price` | Batch asset pricing |
| `POST /lp/state/priced` | LP token price data |
| `GET /stats/tvl` | Protocol TVL snapshot |

Interactive OpenAPI endpoints are currently disabled for every environment. The canonical frontend-to-backend contract is maintained in the parent Cometa platform documentation.

## Configuration and Security

All direct Python dependencies and the Tinyman Git revision are pinned in `Pipfile`;
`Pipfile.lock` fixes the complete graph. Runtime settings are defined in `env.py`
and loaded from environment variables. `.env.example` contains names and safe
placeholders only. Private npm access uses `NODE_AUTH_TOKEN`; Algorand credentials
are checked with:

```bash
pipenv run python scripts/verify_algorand_credentials.py
```

Never commit mnemonics, API keys, `.env` files, or generated recovery data. Credentials used by historical maintenance scripts must be rotated before publishing a repository, even after the files are removed from the current tree.

## Testing and Delivery

GitHub Actions verifies the lockfile, runs Ruff lint and format checks, strictly
type-checks the new domain boundaries, executes every Python test with focused
coverage, checks the Node.js lock contract and entrypoints, and validates Compose
on every pull request and push to `main`. New fixes should include a regression test, with
priority given to:

1. deterministic replay and idempotency of financial events;
2. price freshness and provider fallback behavior;
3. contract registration and API authorization;
4. integer-safe handling of on-chain amounts.

See [`AGENTS.md`](AGENTS.md) for contribution conventions and `docs/audit/01-audit-codebase-2026-07-17.md` for the prioritized architecture roadmap.
