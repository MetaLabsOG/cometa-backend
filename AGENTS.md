# Repository Guidelines

## Project Structure & Module Organization

`app.py` assembles the FastAPI application and background workers; `env.py`
defines environment-backed settings. Product routes and legacy models live in
`api/`, Algorand clients in `blockchain/`, and shared persistence and resilience
code in `core/`. New financial use cases are split across `flex/application/`,
pure invariants in `flex/domain/`, and MongoDB adapters in `flex/db/`. Keep DEX
integration details in `dexes/` or `flex/providers/`. Tests mirror these
boundaries under `tests/unit/` and `tests/integration/`.

## Build, Test, and Development Commands

- `make sync` installs the locked Python 3.12 development environment.
- `make run-api` starts an API-only reload loop on port 8000.
- `make run` starts the production-equivalent application entrypoint.
- `make quality` runs lint, format, type, and test checks.
- `docker compose up -d --build` starts the local application, MongoDB, and
  Algorand services.

Copy `.env.example` to `.env` before running the application. Use only generated,
unfunded accounts for development.

## Coding Style & Naming Conventions

Use four spaces and Ruff formatting. Name functions and modules with
`snake_case`, classes with `PascalCase`, and constants with `UPPER_SNAKE_CASE`.
Type public interfaces. Keep financial amounts as integer base units or
`Decimal`; never round-trip them through `float`. Domain modules must remain
independent of network and database clients. Use module-level logging instead of
`print()`, and move blocking SDK calls outside async request paths.

## Testing Guidelines

Use pytest and name tests `test_<behavior>`. Every bug fix requires a regression
test. Prefer deterministic unit tests with injected clocks and mocked adapter
boundaries. Use `MONGODB_TEST_URI` only for disposable real-MongoDB integration
tests covering uniqueness, compare-and-set behavior, and crash recovery.

## Commits & Pull Requests

Use focused, lowercase imperative subjects, for example
`fix stale price fallback`. Pull requests must explain the failure mode and
outcome, link a GitHub issue when available, list exact verification commands,
and identify API, migration, configuration, rollout, or rollback effects.

## Security & Data Integrity

Validate every external and on-chain payload before persistence. Outbound asset
operations must remain idempotent and reconcile on-chain before completion.
Never commit or log mnemonics, private keys, tokens, database exports, recovery
artifacts, or unredacted production payloads.
