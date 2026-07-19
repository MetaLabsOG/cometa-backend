# Contributing to Cometa Backend

Thanks for improving Cometa. Changes should preserve financial precision, replay
safety, and frontend compatibility—not only make the happy path pass.

## Development workflow

Create a focused branch from `main`, copy `.env.example` to `.env`, and install
the locked development environment:

```bash
make sync
make run
```

`make run` uses the production-equivalent entrypoint. Use `make run-api` for
API-only hot reload when migrations and background workers are intentionally
out of scope.

Before opening a pull request, run the same gate used by CI:

```bash
make quality
```

Use `make format` to apply Ruff formatting. New domain code targets Python 3.12,
passes strict mypy, and must remain green under the Python 3.14 compatibility
job. Keep I/O in adapters or application services; prefer pure functions and
immutable value objects for pricing, transaction parsing, and other financial
rules.

## Tests

Every bug fix needs a regression test. Add fast unit tests under `tests/unit/`
using the `test_<behavior>.py` naming pattern. Test both the successful result
and the failure boundary, especially for:

- integer or `Decimal` amount handling;
- BSON round trips across the full Algorand `uint64` range;
- duplicate, replayed, reordered, or nested chain events;
- crashes between durable intent, broadcast, reconciliation, marker, and cursor writes;
- stale prices and provider fallback exhaustion;
- retries, timeouts, and circuit-breaker transitions;
- authentication and storage uniqueness.

Mock external networks at the adapter boundary. Never use production credentials,
wallets, or mutable production data in tests.

MongoDB semantics that mocks cannot prove belong under `tests/integration/`.
Run them only against a disposable database:

```bash
MONGODB_TEST_URI=mongodb://127.0.0.1:27017 \
  pipenv run pytest tests/integration -m integration -v
```

## API compatibility

The frontend lives in `../metafarm-frontend` and calls this service through
`src/providers/`. Before changing an endpoint, inspect its consumer. A response
shape or field change must update backend tests, frontend types/providers, and
the shared API contract in the parent Cometa documentation.

## Commits and pull requests

Use concise, imperative commit subjects beginning with a lowercase verb, for
example `fix stale price fallback` or `add transaction replay test`.

A pull request should explain the outcome and failure mode, link its issue or
board item, list exact verification commands, and call out migrations,
configuration changes, rollout order, and rollback steps. Include screenshots
only when the change affects user-visible frontend behavior.

Do not include secrets, private logs, database exports, generated recovery data,
or internal infrastructure identifiers. Report security issues through
[`SECURITY.md`](SECURITY.md), not a public issue.
