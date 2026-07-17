# Security Policy

## Supported Versions

Security fixes are applied to the current `main` branch and the version deployed
at `api.cometa.farm`. Older commits and local development snapshots are not
maintained as separate release lines.

## Reporting a Vulnerability

Do not open a regular issue for a suspected vulnerability. While this repository
is private, authorized collaborators should create a draft under
**Security → Advisories → New draft security advisory**. Enable and verify
GitHub private vulnerability reporting before making the repository public.

Include:

- the affected endpoint, component, or commit;
- reproducible steps and the expected security impact;
- whether funds, signing operations, credentials, or data integrity are at risk;
- a minimal proof of concept with secrets and personal data removed.

You should receive an acknowledgement within three business days. Please allow
time for validation, remediation, credential rotation, and coordinated
disclosure before publishing details.

## Sensitive Areas

The highest-risk boundaries are API authentication, Algorand transaction
signing, the Python/Node.js sidecar, price-oracle fallbacks, and event replay.
Testing must use generated accounts and non-production credentials. Never commit
mnemonics, API keys, `.env` files, database exports, recovery artifacts, or
unredacted logs.
