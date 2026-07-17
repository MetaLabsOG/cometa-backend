# Repository Guidelines

## Project Structure & Module Organization

`app.py` creates the FastAPI application and defines routes; `env.py` owns configuration. Keep database models and background jobs in `api/`, Algorand helpers in `blockchain/`, and shared logic in `core/`. DEX adapters belong in `dexes/`, while Flex-specific APIs, providers, migrations, and pricing data live under `flex/`. Telegram and Farcaster integrations are in `bot/` and `farcaster/`; Node.js interoperability is isolated in `js/`. Operational utilities belong in `scripts/`. The repository currently has no committed `tests/` suite.

Before changing an API contract, inspect the frontend consumers in `~/dev/cometa/metafarm-frontend/src/providers/` and update the canonical contract in `~/dev/cometa/CLAUDE.md`.

## Build, Test, and Development Commands

- `pipenv install` installs Python 3.12 dependencies from `Pipfile`.
- `pipenv run uvicorn app:app --reload --port 8000` starts the local API with reload.
- `docker-compose up -d --build` rebuilds and starts the service stack.
- `docker-compose logs -f app` follows application logs.
- `pipenv run pytest tests/ -v` runs tests after the pytest infrastructure is installed.
- `scripts/redeploy.sh` pulls, rebuilds, and restarts services on the VPS; do not use it as a local development command.

## Coding Style & Naming Conventions

Use four-space indentation and standard Python naming: `snake_case` for functions and modules, `PascalCase` for classes, and uppercase names for constants. Add type annotations to public functions and prefer explicit models over loosely shaped dictionaries. Use a module-level logger (`logger = logging.getLogger(__name__)`) instead of `print()`. Read secrets and environment-specific values through `env.py`; never hardcode them. Avoid blocking SDK or HTTP calls in async request paths.

## Testing Guidelines

New tests should use `pytest`, `pytest-asyncio`, and `httpx.AsyncClient`; use `mongomock` or a dedicated test database for MongoDB code. Name files `tests/test_<feature>.py` and test functions `test_<behavior>`. Prioritize atomic lottery claims, contract CRUD, price fetching, and failure paths. Every bug fix should include a regression test when practical.

## Commit & Pull Request Guidelines

Use concise, lowercase imperative subjects such as `fix null bytes in on-chain state keys`. Update `BOARD.md` before committing related work. Keep commits focused, then push unless explicitly told not to. Pull requests should explain the behavior change, link the task or issue, list verification commands, and call out API, configuration, database, or deployment effects. Include frontend updates when response shapes or endpoints change.

## Security & Data Integrity

Validate all external and on-chain input. Preserve Algorand amounts and identifiers without lossy numeric conversion. Do not log credentials, tokens, private keys, or full sensitive payloads.
