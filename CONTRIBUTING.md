# Contributing to Cometa Backend

Thanks for improving Cometa. Changes should preserve financial precision, replay
safety, and frontend compatibility—not only make the happy path pass.

## Development workflow

Create a focused branch from `main`, prepare local settings, and install the
locked development environment:

```bash
cp .env.example .env
make sync
make run-api
```

Before starting the API, follow the
[`README` quick start](README.md#quick-start) to generate an unfunded
development mnemonic and configure the MongoDB and Algorand endpoints.
`make run-api` is the safe API-only development loop. `make run` uses the
production-equivalent entrypoint and may start configured background workers.

Before opening a pull request, run the local Python quality gate:

```bash
make quality
```

Use `make format` to apply Ruff formatting. New domain code targets Python 3.12,
passes strict mypy, and must remain green under the Python 3.14 compatibility
job. Keep I/O in adapters or application services; prefer pure functions and
immutable value objects for pricing, transaction parsing, and other financial
rules.

CI additionally verifies the lockfile and Compose configuration, builds and
scans the production image, scans reachable Git history for secrets, and runs
financial integration tests against disposable MongoDB.

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

The public
[`metafarm-frontend`](https://github.com/MetaLabsOG/metafarm-frontend)
repository consumes this service through `src/providers/`. Before changing an
endpoint, inspect its consumer. A response shape or field change must update
backend tests and the corresponding frontend types and provider calls.

## Commits and pull requests

Use concise, imperative commit subjects beginning with a lowercase verb, for
example `fix stale price fallback` or `add transaction replay test`.

A pull request should explain the outcome and failure mode, link its issue when
available, list exact verification commands, and call out migrations,
configuration changes, rollout order, and rollback steps. Include screenshots
only when the change affects user-visible frontend behavior.

Do not include secrets, private logs, database exports, generated recovery data,
or internal infrastructure identifiers. Report security issues through
[`SECURITY.md`](SECURITY.md), not a public issue.
